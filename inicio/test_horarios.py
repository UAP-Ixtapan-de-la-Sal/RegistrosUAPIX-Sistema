"""Normalización del stash integrada con el historial actual del sistema."""

from datetime import time, timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db.models import F
from django.test import TestCase
from django.utils import timezone

from .models import EventoTallerConferencia, Persona, UsuarioSistema


class HorariosAuditoriaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.persona = Persona.objects.create(
            matricula='DOC-HOR', nombre='Ana', apellidos='Prueba', perfil='Docente',
        )
        cls.user = UsuarioSistema.objects.create_superuser(username='horarios', password='prueba')

    def evento(self, nombre='Evento', inicio=time(9, 30, 59), fin=time(10, 30, 59)):
        obj = EventoTallerConferencia(
            nombre_evento=nombre, ponente_interno=self.persona,
            fecha=timezone.localdate() + timedelta(days=1),
            hora_inicio=inicio, hora_fin=fin,
        )
        obj._history_user = self.user
        obj._change_reason = 'Prueba de horarios'
        return obj

    def test_bulk_create_normalizes_and_records_history_and_author(self):
        saved = EventoTallerConferencia.objects.bulk_create([self.evento('Primero'), self.evento('Segundo')])
        self.assertEqual(len(saved), 2)
        self.assertEqual(EventoTallerConferencia.history.count(), 2)
        for obj in saved:
            obj.refresh_from_db()
            record = obj.history.get()
            self.assertEqual(obj.hora_inicio, time(9, 30))
            self.assertEqual(record.hora_inicio, obj.hora_inicio)
            self.assertEqual(record.history_user, self.user)
            self.assertEqual(record.history_change_reason, 'Prueba de horarios')

    def test_bulk_update_respects_filters_and_history_contains_only_saved_rows(self):
        first, second = EventoTallerConferencia.objects.bulk_create([self.evento('Primero'), self.evento('Segundo')])
        for obj in (first, second):
            obj.hora_inicio = time(11, 15, 59)
            obj.hora_fin = time(12, 15, 59)
        count = EventoTallerConferencia.objects.filter(pk=first.pk).bulk_update(
            [first, second], ['hora_inicio', 'hora_fin'],
        )
        self.assertEqual(count, 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.hora_inicio, time(11, 15))
        self.assertEqual(second.hora_inicio, time(9, 30))
        self.assertEqual(first.history.count(), 2)
        self.assertEqual(second.history.count(), 1)
        self.assertEqual(first.history.latest().history_user, self.user)
        self.assertEqual(first.history.latest().history_type, '~')

    def test_queryset_update_preserves_history_even_when_filter_field_changes(self):
        obj = self.evento('Nombre anterior')
        obj.save()
        updated = EventoTallerConferencia.objects.filter(nombre_evento='Nombre anterior').update(
            nombre_evento='Nombre nuevo', hora_inicio='11:00:59', hora_fin='12:00:59',
        )
        self.assertEqual(updated, 1)
        obj.refresh_from_db()
        record = obj.history.latest()
        self.assertEqual(obj.hora_inicio, time(11, 0))
        self.assertEqual(record.nombre_evento, 'Nombre nuevo')
        self.assertEqual(record.hora_inicio, obj.hora_inicio)
        self.assertEqual(obj.history.count(), 2)

    def test_invalid_row_rolls_back_entire_queryset_update(self):
        first, second = EventoTallerConferencia.objects.bulk_create([
            self.evento('Primero', time(9, 0), time(10, 0)),
            self.evento('Segundo', time(9, 0), time(9, 40)),
        ])
        with self.assertRaises(ValidationError):
            EventoTallerConferencia.objects.all().update(hora_inicio='09:45:59')
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.hora_inicio, time(9, 0))
        self.assertEqual(second.hora_inicio, time(9, 0))
        self.assertEqual(EventoTallerConferencia.history.count(), 2)

    def test_failed_history_write_rolls_back_bulk_creation(self):
        with patch('simple_history.manager.HistoryManager.bulk_history_create', side_effect=RuntimeError('Fallo de historial')):
            with self.assertRaises(RuntimeError):
                EventoTallerConferencia.objects.bulk_create([self.evento()])
        self.assertFalse(EventoTallerConferencia.objects.exists())
        self.assertFalse(EventoTallerConferencia.history.exists())

    def test_conflict_skipping_is_rejected_before_inserting_audited_events(self):
        for option in ('ignore_conflicts', 'update_conflicts'):
            with self.assertRaises(ValueError):
                EventoTallerConferencia.objects.bulk_create([self.evento()], **{option: True})
        self.assertFalse(EventoTallerConferencia.objects.exists())
        self.assertFalse(EventoTallerConferencia.history.exists())

    def test_time_expressions_are_rejected_without_changing_records(self):
        obj = self.evento()
        obj.save()
        with self.assertRaises(ValueError):
            EventoTallerConferencia.objects.filter(pk=obj.pk).update(hora_inicio=F('hora_fin'))
        obj.refresh_from_db()
        self.assertEqual(obj.hora_inicio, time(9, 30))
        self.assertEqual(obj.history.count(), 1)
