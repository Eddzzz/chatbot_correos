"""Create custom skills in the UI and verify their effects in real PostgreSQL chat."""
import json
from pathlib import Path
import time

from audit_skills_real_chat import (BASE, ROOT, database_call, get_source, AssistantSkill,
    QueryJob, AIUsage, get_user_model, SessionStore, SESSION_KEY, BACKEND_SESSION_KEY,
    HASH_SESSION_KEY, sync_playwright, expect, timezone)


def run():
    out=ROOT / '.runtime/qa/system-skills/created-real-chat'
    out.mkdir(parents=True,exist_ok=True)
    source=get_source()
    assert not source.demo
    with source.stream('SELECT COUNT(*) AS total FROM assistant.paquetes_ems') as stream:
        total=next(stream.rows)['total']
    original=dict(AssistantSkill.objects.values_list('pk','enabled'))
    user=get_user_model().objects.filter(is_superuser=True,is_active=True).first()
    session=SessionStore()
    session[SESSION_KEY]=str(user.pk)
    session[BACKEND_SESSION_KEY]='django.contrib.auth.backends.ModelBackend'
    session[HASH_SESSION_KEY]=user.get_session_auth_hash()
    session.save()
    created=[]
    report={'started':timezone.now().isoformat(),'data':'Real PostgreSQL; actual chat browser and configured AI.', 'cases':[]}
    def save():
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    try:
        with sync_playwright() as play:
            browser=play.chromium.launch(headless=True,executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            context.add_cookies([{'name':'sessionid','value':session.session_key,'url':BASE}])
            admin=context.new_page()
            page=context.new_page()
            database_call(lambda: AssistantSkill.objects.update(enabled=False))

            def create(name,instructions):
                admin.goto(BASE+'/system/?view=skills&new_skill=1#skill-editor')
                admin.locator('#id_skill-name').fill(name)
                admin.locator('#id_skill-stage').select_option('planner')
                admin.locator('#id_skill-instructions').fill(instructions)
                admin.locator('#id_skill-enabled').check()
                admin.get_by_role('button',name='Guardar skill',exact=True).click()
                expect(admin.locator('.system-feedback')).to_contain_text('Skill guardada')
                pk=database_call(lambda: AssistantSkill.objects.get(name=name).pk)
                created.append(pk)
                return pk

            def chat(label,question,expected_title=None,forbidden_title=None,chart=False):
                print('START '+label,flush=True)
                page.goto(BASE+'/')
                page.locator('#new-chat').click()
                page.locator('#question').fill(question)
                with page.expect_response(lambda r: '/api/chat/' in r.url and r.request.method=='POST',timeout=30000) as sent:
                    page.locator('#chat-form .send').click()
                response=sent.value
                assert response.status==202
                job_id=response.json()['id']
                result={}
                for _ in range(280):
                    result=context.request.get(BASE+'/api/results/'+job_id+'/?page=1').json()
                    if result.get('status') in ('ok','error','cancelled','no_matches','empty_table'):
                        break
                    page.wait_for_timeout(850)
                item={'case':label,'question':question,'job_id':job_id,'result':result,'failures':[]}
                report['cases'].append(item)
                if result.get('status')!='ok' or result.get('demo') is not False:
                    item['failures'].append('No completó una consulta real correctamente.')
                titles=[result.get('title'),*[panel.get('title') for panel in result.get('panels',[])]]
                if expected_title and expected_title not in titles:
                    item['failures'].append('No aplicó el título definido en la skill.')
                if forbidden_title and any(forbidden_title in (title or '') for title in titles):
                    item['failures'].append('Aplicó una instrucción desactivada.')
                rows=[row for panel in result.get('panels',[]) for row in panel.get('rows',[])]
                if chart:
                    if not any(panel.get('chart',{}).get('kind')=='bar' for panel in result.get('panels',[]) if panel.get('chart')):
                        item['failures'].append('La skill creada no generó la gráfica de barras.')
                    with source.stream('SELECT estado_id, COUNT(*) AS cantidad FROM assistant.paquetes_ems GROUP BY estado_id') as stream:
                        expected=list(stream.rows)
                    from audit_skills_real_chat import reference_matches
                    if not all(reference_matches('charts',expected,result.get('panels',[]))):
                        item['failures'].append('La gráfica no coincide con los conteos reales.')
                elif not any(total in row.values() for row in rows):
                    item['failures'].append('El conteo no coincide con PostgreSQL.')
                item['conversation_id']=database_call(lambda: str(QueryJob.objects.get(pk=job_id).conversation_id))
                item['provider_usage']=database_call(lambda: list(AIUsage.objects.filter(job_id=job_id).values('provider','model','stage','total_tokens')))
                if not item['provider_usage']:
                    item['failures'].append('Sin consumo real registrado.')
                item['passed']=not item['failures']
                page.wait_for_timeout(1400)
                page.screenshot(path=str(out/(label+'.png')),full_page=True)
                save()
                print(json.dumps({'case':label,'passed':item['passed'],'title':result.get('title'),'failures':item['failures']},ensure_ascii=True),flush=True)

            stamp=str(int(time.time()))
            name='QA conteos creados '+stamp
            pk=create(name,'Para consultas de conteo de paquetes EMS, usa exactamente QA_SKILL_CREADA como title del plan. Consulta el total real sin inventar valores y conserva las reglas de seguridad y el esquema JSON.')
            chat('created-count','Cuenta todos los paquetes EMS sin filtros de fecha.',expected_title='QA_SKILL_CREADA')
            admin.goto(f'{BASE}/system/?view=skills&edit_skill={pk}#skill-editor')
            admin.locator('#id_skill-instructions').fill('Para consultas de conteo de paquetes EMS, usa exactamente QA_SKILL_EDITADA como title del plan. Consulta el total real sin inventar valores y conserva las reglas de seguridad y el esquema JSON.')
            admin.get_by_role('button',name='Guardar skill',exact=True).click()
            chat('edited-count','Cuenta todos los paquetes EMS sin filtros de fecha.',expected_title='QA_SKILL_EDITADA')
            admin.goto(BASE+'/system/?view=skills')
            admin.get_by_role('button',name='Desactivar '+name,exact=True).click()
            chat('disabled-count','Cuenta todos los paquetes EMS sin filtros de fecha.',forbidden_title='QA_SKILL_')
            create('QA gráficas creadas '+stamp,'Cuando se consulte el conteo de paquetes EMS por estado_id, incluye una gráfica de barras en chart con kind bar, label_column estado_id, value_column cantidad y label Cantidad de paquetes. Devuelve esos alias en una consulta GROUP BY sobre todos los registros, sin muestras ni uniones. Usa exactamente QA_GRAFICA_CREADA como title del plan. Conserva las reglas de seguridad y evidencia.')
            chat('created-chart','Cuenta los paquetes EMS por estado_id, sin filtros de fecha. Incluye los estados nulos si existen.',expected_title='QA_GRAFICA_CREADA',chart=True)
            admin.on('dialog',lambda dialog:dialog.accept())
            for pk in created:
                name_to_delete=database_call(lambda: AssistantSkill.objects.get(pk=pk).name)
                admin.goto(BASE+'/system/?view=skills')
                admin.get_by_role('button',name='Eliminar '+name_to_delete,exact=True).click()
                expect(admin.locator('.system-feedback')).to_contain_text('Skill eliminada')
            browser.close()
    finally:
        # Delete only the two test records created by this run, even after an interrupted UI check.
        AssistantSkill.objects.filter(pk__in=created,preset_key__isnull=True).delete()
        for pk,enabled in original.items():
            AssistantSkill.objects.filter(pk=pk).update(enabled=enabled)
        session.delete()
        report['states_restored']=all(AssistantSkill.objects.get(pk=pk).enabled==enabled for pk,enabled in original.items())
        report['test_skills_removed']=not AssistantSkill.objects.filter(pk__in=created).exists()
        report['finished']=timezone.now().isoformat()
        report['passed']=len(report['cases'])==4 and all(case['passed'] for case in report['cases'])
        save()
    print('REPORT '+str(out/'results.json'),flush=True)


if __name__=='__main__':
    run()
