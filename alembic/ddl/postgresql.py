import re

from .. import compat
from .base import compiles, alter_table, format_table_name, RenameTable
from .impl import DefaultImpl
from sqlalchemy.dialects.postgresql import INTEGER, BIGINT
from sqlalchemy import text
import logging

log = logging.getLogger(__name__)


class PostgresqlImpl(DefaultImpl):
    __dialect__ = 'postgresql'
    transactional_ddl = True

    def compare_server_default(self, inspector_column,
                               metadata_column,
                               rendered_metadata_default,
                               rendered_inspector_default):
        # don't do defaults for SERIAL columns
        if metadata_column.primary_key and \
                metadata_column is metadata_column.table._autoincrement_column:
            return False

        conn_col_default = rendered_inspector_default

        if None in (conn_col_default, rendered_metadata_default):
            return conn_col_default != rendered_metadata_default

        if metadata_column.server_default is not None and \
            isinstance(metadata_column.server_default.arg,
                       compat.string_types) and \
                not re.match(r"^'.+'$", rendered_metadata_default):
            rendered_metadata_default = "'%s'" % rendered_metadata_default

        return not self.connection.scalar(
            "SELECT %s = %s" % (
                conn_col_default,
                rendered_metadata_default
            )
        )

    def autogen_column_reflect(self, inspector, table, column_info):
        if column_info.get('default') and \
                isinstance(column_info['type'], (INTEGER, BIGINT)):
            seq_match = re.match(
                r"nextval\('(.+?)'::regclass\)",
                column_info['default'])
            if seq_match:
                info = inspector.bind.execute(text(
                    "select c.relname, a.attname "
                    "from pg_class as c join pg_depend d on d.objid=c.oid and "
                    "d.classid='pg_class'::regclass and "
                    "d.refclassid='pg_class'::regclass "
                    "join pg_class t on t.oid=d.refobjid "
                    "join pg_attribute a on a.attrelid=t.oid and "
                    "a.attnum=d.refobjsubid "
                    "where c.relkind='S' and c.relname=:seqname"
                ), seqname=seq_match.group(1)).first()
                if info:
                    seqname, colname = info
                    if colname == column_info['name']:
                        log.info(
                            "Detected sequence named '%s' as "
                            "owned by integer column '%s(%s)', "
                            "assuming SERIAL and omitting" % (
                                seqname, table.name, colname
                            ))
                        # sequence, and the owner is this column,
                        # its a SERIAL - whack it!
                        del column_info['default']


@compiles(RenameTable, "postgresql")
def visit_rename_table(element, compiler, **kw):
    return "%s RENAME TO %s" % (
        alter_table(compiler, element.table_name, element.schema),
        format_table_name(compiler, element.new_table_name, None)
    )
