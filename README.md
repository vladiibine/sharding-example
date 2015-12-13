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
