from datetime import datetime
from optparse import make_option
import time

from django.conf import settings
from django.core.management.base import CommandError, BaseCommand
from django.db import connections
from django.db.models.loading import get_app

from sqlshards.db.partitions.helpers import get_sharded_id_sequence_name
from sqlshards.db.partitions.models import generate_child_partition, replace_pk

# Partitioning limitations:
#   - Indexes, ALTER TABLE ... RENAME, and INSERT do not operate as expected
#     on the parent table.  Each child table must have their own indexes (as
#     well as unique and FK constraints).  The initial SQL generated here
#     handles these cases already.
#
#   - INSERT/UPDATE RETURNING clause does not work.  We could add support
#     (see: http://people.planetpostgresql.org/dfetter/index.php?/archives/59-Partitioning-Glances.html)
#     but this causes an additional insert per insert.  This also causes some
#     odd behavior when trying to migrate data (you have to write to the child
#     table directly instead of the parent table).  We don't use a sequence on
#     the same database (and thus set the pk when saving), so this shouldn't be
#     an issue.
#
#   - UPDATE will not migrate data from one partition to another.  The
#     application must handle this manually.  Again, this can be supported,
#     but introduces a huge conditional case for each combination
#     (see: http://people.planetpostgresql.org/dfetter/index.php?/archives/51-Partitioning-Is-Such-Sweet-Sorrow.html)


class Command(BaseCommand):
    help = 'Generates DML for partitioned tables (expects argument in the '\
           'form <app>.<model>).'

    option_list = BaseCommand.option_list + (
        make_option('--num', action='store', type='int', dest='num_children', default=settings.FORUM_PARTITION_COUNT,
                    help='number of partition tables to create [default: %d]' % (settings.FORUM_PARTITION_COUNT)),
        make_option('--shard', action='store', type='int', dest='shard', default=0,
                    help='physical shard number to generate DDL for (0-based) [default: 0]'),
        make_option('--shards', action='store', type='int', dest='shards', default=1,
                    help='number of physical shards [default: 1]'),
        # TODO: suffix
    )

    def get_children_table_sql(self, model, known_models, num_children, shard_range):
        output = []
        opts = model._meta

        def get_child_table_sql(child_num):
            child = generate_child_partition(model, child_num)
            child = replace_pk(child)

            output, references = self.connection.creation.sql_create_model(child, self.style, [model, child])
            return output

        for i in shard_range:
            output.extend(get_child_table_sql(i))

        # Generate indexes for tables.
        original_db_table = opts.db_table
        for i in shard_range:
            # TODO: suffix
            opts.db_table = '%s_%s' % (original_db_table, i)
            output.extend(self.connection.creation.sql_indexes_for_model(model, self.style))
        opts.db_table = original_db_table

        # ALTERs for check constraint on children table.
        migrations = []
        for i in shard_range:
            child = generate_child_partition(model, i)
            child = replace_pk(child)
            if isinstance(child._shards.key, basestring):
                shard_key_repr = child._shards.key
                shard_key_expr = '"%s"' % shard_key_repr
            else:
                shard_key_repr = '_'.join(child._shards.key)
                # TODO: This sums the keys for the expression right now.
                # This needs to match the logic in MasterShardOptions.get_key_from_kwargs.
                shard_key_expr = '("' + '" + "'.join(child._shards.key) + '")'

            constraint_name = "%s_%s_check_modulo" % (child._meta.db_table, shard_key_repr)
            output.append(self.style.SQL_KEYWORD('ALTER TABLE ') +
                self.style.SQL_TABLE('"' + child._meta.db_table + '"') +
                self.style.SQL_KEYWORD(' ADD CONSTRAINT ') +
                self.style.SQL_FIELD('"' + constraint_name + '"') +
                self.style.SQL_KEYWORD(' CHECK ') +
                '(%s %% %d = %d);' % (shard_key_expr, num_children, i))

            # Temporary ALTER TABLEs to use new sequences until we've fully
            # transitioned all old tables.
            migrations.append('ALTER TABLE "{0}" ALTER COLUMN id SET DEFAULT next_sharded_id(\'{0}_id_seq\', {1});'.format(child._meta.db_table, i))

        return output + migrations

    def get_sequences(self, model, num_children, shard_range):
        output = []

        our_epoch = int(time.mktime(datetime(2012, 11, 1).timetuple()) * 1000)
        proc = """CREATE OR REPLACE FUNCTION next_sharded_id(varchar, int, OUT result bigint) AS $$
DECLARE
    sequence_name ALIAS FOR $1;
    shard_id ALIAS FOR $2;

    seq_id bigint;
    now_millis bigint;
BEGIN
    SELECT nextval(sequence_name::regclass) % 1024 INTO seq_id;

    SELECT FLOOR(EXTRACT(EPOCH FROM clock_timestamp()) * 1000) INTO now_millis;
    result := (now_millis - {our_epoch}) << 23;
    result := result | (shard_id << 10);
    result := result | (seq_id);
END;
$$ LANGUAGE PLPGSQL;""".format(our_epoch=our_epoch)
        output.append(self.style.SQL_KEYWORD(proc))

        for i in shard_range:
            child = generate_child_partition(model, i)
            child = replace_pk(child)
            output.append(self.style.SQL_KEYWORD("CREATE SEQUENCE ") +
               self.style.SQL_TABLE(get_sharded_id_sequence_name(child)) + ";")

        return output

    def get_partitioned_model(self, app, model):
        for obj in (getattr(app, x) for x in dir(app)):
            if not hasattr(obj, '_shards') or not obj._shards.is_master:
                continue

            if obj._meta.module_name == model:
                return obj
        raise ValueError

    def handle(self, *args, **options):
        try:
            app, model = args[0].split('.')
        except ValueError:
            raise CommandError('Expected argument <app>.<model>')

        self.connection = connections['default']

        # XXX: We cant use get_model because its now an abstract model
        # model = get_model(app, model)
        app = get_app(app)
        model = self.get_partitioned_model(app, model)

        num_children = options['num_children']
        shard_range = range(options['shard'], num_children, options['shards'])
        known_models = [model]

        # Known models are only models visible to the partitioned database
        # cluster.
        # for app in get_apps():
        #     if '.' in app:
        #         app, mod = app.split('.')
        #         known_models.append(get_model(app, mod))
        #     else:
        #         known_models.extend(get_models(app), inclue_auto_created=True)

        output = self.get_sequences(model, num_children, shard_range)
        output.extend(self.get_children_table_sql(model, known_models, num_children, shard_range))

        return u'\n\n'.join(output) + '\n'