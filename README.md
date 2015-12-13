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
