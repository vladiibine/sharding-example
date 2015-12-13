# sharding-example
Example of sharding tools used at Disqus

Fork, to make it work!

### Setting up postgres

##### Creating 2 postgresql clusters locally:
`$ pg_createcluster 9.3 shard1`
After this is done, check out the port for this cluster (likely 5433)

`$ pg_createcluster 9.3 shard2`
Also check the port for this cluster (likely 5434)

##### Create for each one a superuser:
`$ sudo su - postgres`
function next_sharded_id(unknown, integer) does not exist

`$ psql -p 5433` You'll need credentials here

`postgres=# create role testrole with superuser createdb login password 'asdf';`  

Do this for the other cluster too (use `-p 5434`)

You'll then need to make sure the database `sharded_polls` exists on both new clusters:

`postgres=# create database sharded_polls;`

##### Some manual hacks (I'll make a mgmt command at some point)
Go to the python shell like this:
`$ ./manage.py shell`

`$ from sqlshards.db.shards.sql import next_sharded_id`

`$ print next_sharded_id`

Then, go to the psql shell, connect to the sharded_polls databases, on each shard, and paste the result you got in the python shell - it should create a function.

For reference, it should look like this

```
CREATE OR REPLACE FUNCTION next_sharded_id(varchar, int, OUT result bigint) AS $$
DECLARE
    sequence_name ALIAS FOR $1;
    shard_id ALIAS FOR $2;

    seq_id bigint;
    now_millis bigint;
BEGIN
    SELECT nextval(sequence_name::regclass) % 1024 INTO seq_id;

    SELECT FLOOR(EXTRACT(EPOCH FROM clock_timestamp()) * 1000) INTO now_millis;
    result := (now_millis - 1351720800000) << 23;
    result := result | (shard_id << 10);
    result := result | (seq_id);
END;
$$ LANGUAGE PLPGSQL;
```

Now `./manage.py syncdb should work`.

But of course, you need to run that on all your databases, so run with flag
`./manage.py --database=sharded.shard0` and `sharded.shard1`

##### More manual steps:
You're now ready to run the `sqlpartition` command provided by the sqlshards app

`$ ./manage.py sqlpartition polls.Choice`

This will output some SQL that looks like this:
```
CREATE OR REPLACE FUNCTION next_sharded_id(varchar, int, OUT result bigint) AS $$
DECLARE
    sequence_name ALIAS FOR $1;
    shard_id ALIAS FOR $2;

    seq_id bigint;
    now_millis bigint;
BEGIN
    SELECT nextval(sequence_name::regclass) % 1024 INTO seq_id;

    SELECT FLOOR(EXTRACT(EPOCH FROM clock_timestamp()) * 1000) INTO now_millis;
    result := (now_millis - 1351746000000) << 23;
    result := result | (shard_id << 10);
    result := result | (seq_id);
END;
$$ LANGUAGE PLPGSQL;

CREATE SEQUENCE polls_choice_0_id_seq;

CREATE SEQUENCE polls_choice_1_id_seq;

CREATE TABLE "polls_choice_0" (
    "id" bigint DEFAULT next_sharded_id('polls_choice_0_id_seq'::varchar, 0) NOT NULL PRIMARY KEY,
    "poll_id" integer CHECK ("poll_id" >= 0) NOT NULL,
    "choice_text" varchar(200) NOT NULL,
    "votes" integer NOT NULL
)
;

CREATE TABLE "polls_choice_1" (
    "id" bigint DEFAULT next_sharded_id('polls_choice_1_id_seq'::varchar, 1) NOT NULL PRIMARY KEY,
    "poll_id" integer CHECK ("poll_id" >= 0) NOT NULL,
    "choice_text" varchar(200) NOT NULL,
    "votes" integer NOT NULL
)
;

CREATE INDEX "polls_choice_0_poll_id" ON "polls_choice_0" ("poll_id");

CREATE INDEX "polls_choice_1_poll_id" ON "polls_choice_1" ("poll_id");

ALTER TABLE "polls_choice_0" ADD CONSTRAINT "polls_choice_0_poll_id_check_modulo" CHECK (("poll_id") % 2 = 0);

ALTER TABLE "polls_choice_1" ADD CONSTRAINT "polls_choice_1_poll_id_check_modulo" CHECK (("poll_id") % 2 = 1);

ALTER TABLE "polls_choice_0" ALTER COLUMN id SET DEFAULT next_sharded_id('polls_choice_0_id_seq', 0);

ALTER TABLE "polls_choice_1" ALTER COLUMN id SET DEFAULT next_sharded_id('polls_choice_1_id_seq', 1);
```

For some reason, the tables were already created by syncdb. We'll now only have to execute manually some of these commands, such as these, on our first shard (shard0):

```
CREATE SEQUENCE polls_choice_0_id_seq;

CREATE INDEX "polls_choice_0_poll_id" ON "polls_choice_0" ("poll_id");

ALTER TABLE "polls_choice_0" ADD CONSTRAINT "polls_choice_0_poll_id_check_modulo" CHECK (("poll_id") % 2 = 0);

ALTER TABLE "polls_choice_0" ALTER COLUMN id SET DEFAULT next_sharded_id('polls_choice_0_id_seq', 0);
```

Also, run the remaining commands on shard1
```
CREATE SEQUENCE polls_choice_1_id_seq;

CREATE INDEX "polls_choice_1_poll_id" ON "polls_choice_1" ("poll_id");

ALTER TABLE "polls_choice_1" ADD CONSTRAINT "polls_choice_1_poll_id_check_modulo" CHECK (("poll_id") % 2 = 1);

ALTER TABLE "polls_choice_1" ALTER COLUMN id SET DEFAULT next_sharded_id('polls_choice_1_id_seq', 1);
```

The most interesting thing that these commands do is to make sure that on each shard, only a certain subset of IDs will be stored. As such, on shard0, we'll only have even ids, and on shard1 we'll have only the odd ones.
