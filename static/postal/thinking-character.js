(() => {
  "use strict";
  const assetUrl = "/static/postal/assets/cartero-thoughtful-v3.png";
  const vertex = `
    attribute vec2 position;
    varying vec2 uv;
    void main() {
      uv = vec2(position.x * .5 + .5, .5 - position.y * .5);
      gl_Position = vec4(position, 0., 1.);
    }`;
  const fragment = `
    precision mediump float;
    varying vec2 uv;
    uniform sampler2D portrait;
    uniform vec3 pose;
    uniform float blink;
    float eyeMask(vec2 p, vec2 center, vec2 radius) {
      return 1. - smoothstep(.8, 1.15, length((p - center) / radius));
    }
    void main() {
      // One continuous surface keeps the neck, chin and fingers connected.
      vec2 p = uv;
      float head = 1. - smoothstep(.47, .74, p.y);
      vec2 pivot = vec2(.52, .59);
      vec2 d = p - pivot;
      float a = pose.x * head;
      p = pivot + mat2(cos(a), -sin(a), sin(a), cos(a)) * d;
      p.y += pose.y * (1. - smoothstep(.4, .98, uv.y));
      p.x += pose.z * (1. - smoothstep(.35, .94, uv.y));
      if (p.x < 0. || p.x > 1. || p.y < 0. || p.y > 1.) {
        gl_FragColor = vec4(0.); return;
      }
      vec4 open = texture2D(portrait, vec2(p.x * .5, p.y));
      vec4 shut = texture2D(portrait, vec2(.5 + p.x * .5, p.y));
      float left = eyeMask(p, vec2(.449, .364), vec2(.064, .062));
      float right = eyeMask(p, vec2(.611, .332), vec2(.057, .059));
      float eyelidY = mix(.25, .46, blink);
      float lid = 1. - smoothstep(eyelidY - .012, eyelidY + .012, p.y);
      // Only eyelids change texture; the face never swaps between drawings.
      gl_FragColor = mix(open, shut, max(left, right) * lid);
    }`;

  function mount(scene) {
    const canvas = document.createElement("canvas");
    canvas.className = "thinking-character";
    canvas.setAttribute("aria-hidden", "true");
    const resolution = Math.round(208 * Math.min(devicePixelRatio || 1, 2));
    canvas.width = canvas.height = resolution;
    scene.append(canvas);
    const gl = canvas.getContext("webgl", {alpha:true, premultipliedAlpha:false, antialias:false});
    if (!gl) return () => canvas.remove();
    let disposed = false, ready = false, visible = true, frame = 0, elapsed = 0, last = null;
    const shaders = [];
    const program = gl.createProgram();
    const buffer = gl.createBuffer();
    const texture = gl.createTexture();
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    function compile(type, source) {
      const shader = gl.createShader(type);
      shaders.push(shader);
      gl.shaderSource(shader, source); gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return false;
      gl.attachShader(program, shader);
      return true;
    }
    const compiled = compile(gl.VERTEX_SHADER, vertex) && compile(gl.FRAGMENT_SHADER, fragment);
    gl.linkProgram(program);
    if (!compiled || !gl.getProgramParameter(program, gl.LINK_STATUS)) {
      gl.deleteBuffer(buffer); gl.deleteTexture(texture); gl.deleteProgram(program);
      shaders.forEach(shader => gl.deleteShader(shader));
      return () => canvas.remove();
    }
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
    const position = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const pose = gl.getUniformLocation(program, "pose");
    const blink = gl.getUniformLocation(program, "blink");
    gl.uniform1i(gl.getUniformLocation(program, "portrait"), 0);
    gl.viewport(0, 0, resolution, resolution);
    function draw(time) {
      const phase = time * Math.PI * 2 / 8;
      gl.uniform3f(pose, .04 * Math.sin(phase) + .009 * Math.sin(phase * 2),
        .0045 * Math.sin(phase * 2 - .4), .004 * Math.sin(phase - .8));
      const cycle = time % 8;
      const pulse = center => Math.exp(-Math.pow((cycle - center) / .095, 2));
      gl.uniform1f(blink, Math.max(pulse(2.1), pulse(6.4)));
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
    function tick(now) {
      frame = 0;
      if (disposed || !ready || document.hidden || !visible || motion.matches) { last = null; return; }
      if (last !== null) elapsed += Math.min((now - last) / 1000, .05);
      last = now;
      draw(elapsed);
      frame = requestAnimationFrame(tick);
    }
    function update() {
      cancelAnimationFrame(frame); frame = 0; last = null;
      if (!disposed && ready && !document.hidden && visible && !motion.matches) frame = requestAnimationFrame(tick);
    }
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; update(); });
    observer.observe(scene);
    document.addEventListener("visibilitychange", update);
    motion.addEventListener("change", update);
    canvas.addEventListener("webglcontextlost", () => {
      ready = false; update(); canvas.removeAttribute("data-renderer");
    });
    const image = new Image();
    image.onload = () => {
      if (disposed) return;
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      ready = true; draw(0); canvas.dataset.renderer = "webgl"; update();
    };
    image.src = assetUrl;
    return () => {
      if (disposed) return;
      disposed = true; cancelAnimationFrame(frame); observer.disconnect();
      document.removeEventListener("visibilitychange", update);
      motion.removeEventListener("change", update);
      gl.deleteBuffer(buffer); gl.deleteTexture(texture); gl.deleteProgram(program);
      shaders.forEach(shader => gl.deleteShader(shader));
      canvas.remove();
    };
  }
  window.PostalThinking = {mount};
})();
