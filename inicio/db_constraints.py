"""Expresion CHECK de precision operativa: compatible con MariaDB y SQLite."""
from zoneinfo import ZoneInfo

from django.db import models
from django.db.models.functions import TruncMinute
from django.db.models.lookups import Exact


class PrecisionMinuto(models.Func):
    arity = 1
    output_field = models.BooleanField()

    def as_mysql(self, compiler, connection, **extra_context):
        # Funciones deterministas, sin DATE_FORMAT ni conversion de zona.
        sql, params = compiler.compile(self.source_expressions[0])
        return f'(SECOND({sql}) = 0 AND MICROSECOND({sql}) = 0)', (*params, *params)

    def as_sql(self, compiler, connection, **extra_context):
        source = self.source_expressions[0]
        kwargs = {'tzinfo': ZoneInfo('UTC')} if isinstance(source.output_field, models.DateTimeField) else {}
        return compiler.compile(Exact(source, TruncMinute(source, **kwargs)))
