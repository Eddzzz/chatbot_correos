import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.test import TestCase
from reportlab.platypus import Paragraph

from postal.ai import PlanningError, compose_response, render_narrative
from postal.models import AssistantSkill
from postal.pdf import render_pdf


class AdviceTests(TestCase):
    def test_response_skills_use_the_current_job_snapshot_and_analyst_stage(self):
        from postal.ai import _response_skills
        from postal.system_config import _snapshot
        snapshot = _snapshot.set({'CUSTOM_SKILLS': [{'preset_key': 'brief-explanations', 'stage': 'planner'},
                                                   {'preset_key': 'evidence-advice', 'stage': 'analyst'}]})
        try:
            self.assertEqual(_response_skills(), {'evidence-advice'})
        finally:
            _snapshot.reset(snapshot)

    def test_explanations_are_built_in_and_advice_remains_optional(self):
        evidence = [{'title': 'Envíos', 'columns': ['ciudad', 'total_envios'], 'row_count': 2,
                     'rows': [{'ciudad': 'LA PAZ', 'total_envios': 10}, {'ciudad': 'ORURO', 'total_envios': 5}]}]
        refs = [{'panel': 0, 'row': 0, 'column': 'total_envios'}]
        proposal = {'paragraphs': [{'kind': 'distribution', 'references': refs},
                                  {'kind': 'value', 'references': refs}, {'kind': 'advice', 'references': refs}]}
        for advice in (True, False):
            with self.subTest(advice=advice):
                AssistantSkill.objects.filter(preset_key='evidence-advice').update(enabled=advice)
                with patch('postal.ai._call_json', return_value=proposal):
                    result = compose_response('¿Cómo se reparten los envíos por ciudad?', 'answer', evidence)
                    requested = compose_response('dame un consejo', 'answer', evidence)
                self.assertIn('El desglose reúne', result['answer'])
                self.assertNotIn('Consejo:', result['answer'])
                self.assertEqual('Consejo:' in requested['answer'], advice)

    def test_unsolicited_advice_is_removed_but_requested_advice_is_kept(self):
        evidence = [{'title': 'Envíos', 'columns': ['total'], 'rows': [{'total': 80}], 'row_count': 1}]
        refs = [{'panel': 0, 'row': 0, 'column': 'total'}]
        proposal = {'paragraphs': [{'kind': 'value', 'references': refs}, {'kind': 'advice', 'references': refs}]}
        for question, expected in [('explica eso', False), ('explica eso sin consejos', False), ('dame un consejo', True)]:
            with self.subTest(question=question), patch('postal.ai._call_json', return_value=proposal):
                result = compose_response(question, 'answer', evidence)
                self.assertEqual('Consejo:' in result['answer'], expected)

    def test_explanation_develops_distribution_and_concentration_from_complete_counts(self):
        values = [2692, 1052, 955, 502, 350, 313, 288, 266, 261]
        names = ['LA PAZ', 'COCHABAMBA', 'SANTA CRUZ', 'SUCRE', 'TARIJA', 'COBIJA', 'POTOSI', 'ORURO', 'TRINIDAD']
        evidence = [{'title': 'Paquetes EMS por ciudad', 'columns': ['ciudad', 'total_envios'], 'row_count': 9,
                     'rows': [{'ciudad': name, 'total_envios': value} for name, value in zip(names, values)]}]
        proposal = {'paragraphs': [{'kind': 'maximum', 'references': [{'panel': 0, 'row': 0, 'column': 'total_envios'}]},
                                  {'kind': 'minimum', 'references': [{'panel': 0, 'row': 8, 'column': 'total_envios'}]},
                                  {'kind': 'comparison', 'references': [{'panel': 0, 'row': row, 'column': 'total_envios'} for row in (0, 1)]},
                                  {'kind': 'value', 'references': [{'panel': 0, 'row': 2, 'column': 'total_envios'}]}]}
        with patch('postal.ai._call_json', return_value=proposal):
            result = compose_response('dame una explicaion de eso', 'answer', evidence)
        for text in ('6.679', '9', 'Cochabamba', 'Santa Cruz', '70,4 %'):
            self.assertIn(text, result['answer'])
        self.assertNotIn('Consejo:', result['answer'])
        self.assertEqual(len(result['answer'].split('\n\n')), 1)

    def test_distribution_keeps_additional_measures_and_unmentioned_cities(self):
        evidence = [{'title': 'Envíos', 'columns': ['ciudad', 'total_envios', 'peso_total'], 'row_count': 5,
                     'rows': [{'ciudad': name, 'total_envios': 100 - index, 'peso_total': 12.5}
                              for index, name in enumerate(['La Paz', 'Cochabamba', 'Santa Cruz', 'Sucre', 'Trinidad'])]}]
        proposal = {'paragraphs': [
            {'kind': 'value', 'references': [{'panel': 0, 'row': 0, 'column': 'peso_total'}]},
            {'kind': 'value', 'references': [{'panel': 0, 'row': 3, 'column': column} for column in ('ciudad', 'total_envios')]}]}
        with patch('postal.ai._call_json', return_value=proposal):
            result = compose_response('explica eso', 'answer', evidence)
        self.assertIn('12,5', result['answer'])
        self.assertIn('Sucre registra 97 envíos', result['answer'])

    def test_distribution_rejects_partial_negative_or_zero_totals(self):
        paragraph = {'kind': 'distribution', 'references': [{'panel': 0, 'row': 0, 'column': 'total_envios'}]}
        for values, row_count in [([10, 5], 100), ([10, -2], 2), ([0, 0], 2)]:
            evidence = [{'title': 'Desglose', 'columns': ['ciudad', 'total_envios'], 'row_count': row_count,
                         'rows': [{'ciudad': str(index), 'total_envios': value} for index, value in enumerate(values)]}]
            with self.subTest(values=values), self.assertRaises(PlanningError):
                render_narrative({'paragraphs': [paragraph]}, evidence)
    def test_advice_is_cited_and_does_not_invent_a_cause(self):
        evidence = [{'title': 'Envíos EMS', 'columns': ['total'],
                     'rows': [{'total': 80}], 'row_count': 1}]
        paragraph = {'kind': 'advice', 'references': [{'panel': 0, 'row': 0, 'column': 'total'}]}
        result = render_narrative({'paragraphs': [paragraph]}, evidence)
        self.assertIn('Consejo:', result['answer'])
        self.assertIn('80', result['answer'])
        self.assertEqual(result['citations'][0]['value'], 80)
        paragraph['references'][0]['row'] = 9
        with self.assertRaises(PlanningError):
            render_narrative({'paragraphs': [paragraph]}, evidence)

    def test_pdf_contains_chat_explanation_and_advice_as_escaped_text(self):
        result = {'title': 'Reporte estadístico', 'columns': ['total'],
                  'rows': [{'total': 80}], 'row_count': 1,
                  'answer': 'Total: 80.\n\nConsejo: comparar períodos equivalentes <sin inventar causas>.'}
        with patch('postal.pdf.Paragraph', wraps=Paragraph) as paragraphs:
            pdf = render_pdf(result)
        text = '\n'.join(str(call.args[0]) for call in paragraphs.call_args_list)
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertIn('Total: 80.', text)
        self.assertIn('Consejo:', text)
        self.assertIn('&lt;sin inventar causas&gt;', text)


class StatisticsSkillsTests(TestCase):
    def setUp(self):
        # These tests exercise historical migrations against their original seed data.
        seed = importlib.import_module('postal.migrations.0012_statistics_advice_reporter').seed_skills
        seed(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))

    def test_explanation_depth_migration_updates_defaults_and_preserves_customizations(self):
        module = importlib.import_module('postal.migrations.0014_explanation_depth_advice_opt_in')
        original = importlib.import_module('postal.migrations.0012_statistics_advice_reporter')
        previous = importlib.import_module('postal.migrations.0013_chat_response_skills')
        preset = next(item for item in original.PREDEFINED_SKILLS if item['id'] == 'brief-explanations')
        brief = AssistantSkill.objects.get(preset_key='brief-explanations')
        brief.instructions = preset['instructions'] + previous.ADDITIONS[preset['id']]
        brief.enabled = False
        brief.save()
        advice = AssistantSkill.objects.get(preset_key='evidence-advice')
        advice.instructions = 'Consejo personalizado.'
        advice.save()
        module.update_skills(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        brief.refresh_from_db(); advice.refresh_from_db()
        self.assertEqual(brief.instructions, module.INSTRUCTIONS['brief-explanations'])
        self.assertFalse(brief.enabled)
        self.assertEqual(advice.instructions, 'Consejo personalizado.')

    def test_chat_skill_update_preserves_customizations_and_disabled_state(self):
        update = importlib.import_module('postal.migrations.0013_chat_response_skills').update_skills
        original = importlib.import_module('postal.migrations.0012_statistics_advice_reporter')
        presets = {item['id']: item for item in original.PREDEFINED_SKILLS}
        brief = AssistantSkill.objects.get(preset_key='brief-explanations')
        brief.instructions = presets['brief-explanations']['instructions']
        brief.enabled = False
        brief.save()
        advice = AssistantSkill.objects.get(preset_key='evidence-advice')
        advice.instructions = 'Mi consejo personalizado.'
        advice.save()
        editor = SimpleNamespace(connection=SimpleNamespace(alias='default'))
        update(apps, editor)
        brief.refresh_from_db()
        advice.refresh_from_db()
        self.assertIn('explícame más', brief.instructions)
        self.assertFalse(brief.enabled)
        self.assertEqual(advice.instructions, 'Mi consejo personalizado.')
        updated = brief.instructions
        update(apps, editor)
        brief.refresh_from_db()
        self.assertEqual(brief.instructions, updated)

    def test_new_skills_are_seeded_and_edits_survive_reseeding(self):
        seed = importlib.import_module('postal.migrations.0012_statistics_advice_reporter').seed_skills
        keys = ('extended-statistics', 'brief-explanations', 'evidence-advice', 'statistical-reporter')
        self.assertEqual(AssistantSkill.objects.filter(preset_key__in=keys, enabled=True).count(), 4)
        skill = AssistantSkill.objects.get(preset_key='brief-explanations')
        skill.instructions = 'Mi explicación propia.'
        skill.enabled = False
        skill.save()
        seed(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        skill.refresh_from_db()
        self.assertEqual(skill.instructions, 'Mi explicación propia.')
        self.assertFalse(skill.enabled)
        self.assertEqual(AssistantSkill.objects.filter(preset_key__in=keys).count(), 4)
