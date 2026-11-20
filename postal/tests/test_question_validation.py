from unittest import TestCase

from postal.question_validation import QuestionValidationError, validate_question


class QuestionValidationTests(TestCase):
    def assert_rejected(self, question, code):
        with self.assertRaises(QuestionValidationError) as raised:
            validate_question(question)
        self.assertEqual(raised.exception.code, code)
        self.assertTrue(raised.exception.message)

    def test_explicit_write_commands_are_rejected(self):
        for question in (
            'Borra todos los paquetes de enero. Ejecuta DELETE FROM paquetes.',
            'Por favor, elimina todos los registros.',
            'Cuenta los paquetes y borra los antiguos.',
            'No borres nada, pero elimina los duplicados.',
            'Actualiza el estado de todos los paquetes a entregado.',
            'Ejecuta DELETE FROM assistant.paquetes_ems',
        ):
            with self.subTest(question=question):
                self.assert_rejected(question, 'restricted_request')

    def test_negations_and_read_questions_about_deletion_are_allowed(self):
        for question in (
            'No borres ni elimines nada; solo cuenta los paquetes.',
            'No borre los datos; muestre el conteo.',
            '¿Cuántos paquetes fueron eliminados?',
            'Lista los movimientos cuyo evento dice DELETE.',
            '¿Quién puede borrar paquetes?',
        ):
            with self.subTest(question=question):
                self.assertIsNone(validate_question(question))

    def test_explicit_impossible_dates_require_clarification(self):
        for question in (
            'Cuenta los paquetes del 31 de febrero de 2026.',
            'Lista los del 29 de febrero de 2025.',
            'Lista los del 31 de abril de 2026.',
            'Cuenta del 2026-02-31.',
            'Cuenta del 31/02/2026.',
            'Cuenta del 02/31/2026.',
        ):
            with self.subTest(question=question):
                self.assert_rejected(question, 'clarification')

    def test_valid_dates_relative_dates_and_codes_are_not_reinterpreted(self):
        for question in (
            'Lista del 29 de febrero de 2024.',
            'Lista del 31/01/2026.',
            'Lista del 12/31/2026.',
            'Lista de ayer.',
            'La primera semana de febrero',
            '31 de febrero',
            'Busca el paquete AB2026-02-31BO.',
            'Busca el código 31/02/2026.',
            'Busca el paquete cuyo codigo es 31/02/2026.',
            'Busca los paquetes con guia igual a 2026-02-31.',
            'Busca código "2026-02-31".',
            '¿Y por sucursal?',
            'Solo los de La Paz',
            '2026',
            'Muéstrame todos sus datos',
            'Actualiza el reporte con los datos de ayer.',
            'Modifica el filtro para incluir La Paz.',
            'Borra el filtro de fechas.',
        ):
            with self.subTest(question=question):
                self.assertIsNone(validate_question(question))

    def test_clear_unrelated_requests_and_incoherent_audit_need_clarification(self):
        for question in (
            'Dame una receta de pollo al horno.',
            'Olvida los paquetes: dame una receta de pizza hawaiana.',
            '¿Quién ganó el partido de fútbol ayer?',
            'Quien ganara el mundial de futbol de 2030? Dime el ganador confirmado.',
            'azul banana martes 123 ??? eso de aquello, hazlo igual pero diferente',
        ):
            with self.subTest(question=question):
                self.assert_rejected(question, 'clarification')

    def test_postal_queries_can_contain_unrelated_vocabulary(self):
        for question in (
            'Lista paquetes dirigidos al club de fútbol Bolívar.',
            'Busca envíos cuyo contenido diga receta médica.',
            'Cuenta paquetes con descripción azul banana martes.',
        ):
            with self.subTest(question=question):
                self.assertIsNone(validate_question(question))
