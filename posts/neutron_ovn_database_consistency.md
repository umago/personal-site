title: Neutron & OVN database consistency
date: 03-05-2018

In this post I will talk about a problem that affects many (if not all)
drivers in [OpenStack Neutron][0] and how it was solved for the OVN driver
(AKA [networking-ovn][1]).

## Problem description

In a common Neutron deployment model, multiple neutron-servers will
handle the API requests concurrently. Requests which mutate the state
of a resource (create, update and delete) will have their changes first
committed to the Neutron database and then the loaded SDN driver is
invoked to translate that information to its specific data model. As
the following diagram illustrates:

<img src=/posts/images/neutron_deployment_model_diagram.png width=70% class="center" title="Neutron Deployment Model">

The model above can lead to two situations that could cause
inconsistencies between the Neutron and the SDN databases:

### Problem 1: Same resource updates race condition

When two or more updates to the same resource is issued at the same time
and handled by different neutron-servers, the order in which these updates
are written to the Neutron database is correct, however, the methods
invoked in the driver to update the SDN database are not guaranteed to
follow the same order as the Neutron database commits. That could lead
to newer updates being overwritten by old ones on the SDN side resulting
in both databases becoming inconsistent with each other.

The pseudo code for these updates looks something like this:

```
  In Neutron:

    with neutron_db_transaction:
         update_neutron_db()
         driver.update_port_precommit()
    driver.update_port_postcommit()

  In the driver:

    def update_port_postcommit:
        port = neutron_db.get_port()
        update_port_in_southbound_controller(port)
```

This problem has been reported at [bug #1605089][2].

### Problem 2: Backend failures

The second situation is when changes are already fully persisted in
the Neutron database but an error occurs upon trying to update the
SDN database. Usually, what drivers do when that happens is to try to
immediately rollback those changes in Neutron and then throw an error but,
that rollback operation itself could also fail.

On top of that, rollbacks are not very straight forward when it comes
to updates or deletes. For example, in the case where a VM is being
teared down, part of the process includes deleting the ports associated
with that VM. If the port deletion fails on the SDN side, re-creating
that port in Neutron does not fix the problem. The decommission of a VM
involves many other things, in fact, by recreating that port we could
make things even worse because it will leave some dirty data around.

## The [networking-ovn][1] solution

The solution used by the networking-ovn driver relies on the Neutron's
revision_number attribute. In summary, for each resource in the
Neutron database there's an attribute called revision_number which gets
incremented on every update, for example:

```
$ openstack port create --network nettest porttest
...
| revision_number | 2 |
...

$ openstack port set porttest --mac-address 11:22:33:44:55:66

$ mysql -e "use neutron; select standard_attr_id from ports \
where id=\"91c08021-ded3-4c5a-8d57-5b5c389f8e39\";"
+------------------+
| standard_attr_id |
+------------------+
|             1427 |
+------------------+

$ mysql -e "use neutron; SELECT revision_number FROM \
standardattributes WHERE id=1427;"
+-----------------+
| revision_number |
+-----------------+
|               3 |
+-----------------+
```

The revision_number attribute is used by networking-ovn to solve the
inconsistency problem in four situations:

### 1. Storing the revision_number in the OVN database

To be able to compare the version of the resource in Neutron against the
version in OVN we first need to know which version the OVN resource is
present at.

Fortunately, each table in the OVN Northbound database[^1] contains
a special column called external_ids which external systems (such as
Neutron) can use to store information about its own resources that
corresponds to the entries in the OVN database.

In our solution, every time a resource is created or updated by
networking-ovn, the Neutron revision_number related to that change
will be stored in the external_ids column of that resource in the OVN
database. That allows networking-ovn to look at both databases and detect
whether the version in OVN is up-to-date with Neutron or not. Here's
how the revision_number is stored:

```
$ ovn-nbctl list Logical_Switch_Port
...
external_ids        : {"neutron:cidrs"="",
"neutron:device_id"="", "neutron:device_owner"="",
"neutron:network_name"="neutron-139fd18c-cdba-4dfe-8030-2da39c70d238",
"neutron:port_name"=porttest,
"neutron:project_id"="8563f800ffc54189a145033d5402c922",
"neutron:revision_number"="3",
"neutron:security_group_ids"="b7def5c3-8776-4942-97af-2985c4fdccea"}
...

```

### 2. Performing a [compare-and-swap][4] operation based on the revision_number

To ensure correctness when updating the OVN database, specifically when
multiple updates are racing to change the same resource, we need to
prevent older updates from overwritten newer ones.

The solution we found for this problem was to create a special [OVSDB
command][5] that runs as part of the transaction which is updating
the resource in the OVN database and prevent changes with a lower
revision_number to be committed. To achieve this, the [OVSDB command][5]
does two things:

1 - Add a [verify operation][6] to the external_ids column in the OVN
database so that if another client modifies that column mid-operation
the transaction will be restarted.

A better explanation of what "verify" does is described in the doc
string of the Transaction class in the [OVS code][7] itself, I quote:

> "Because OVSDB handles multiple clients, it can happen that between
> the time that OVSDB client A reads a column and writes a new value,
> OVSDB client B has written that column. Client A's write should not
> ordinarily overwrite client B's, especially if the column in question
> is a "map" column that contains several more or less independent
> data items. If client A adds a "verify" operation before it writes
> the column, then the transaction fails in case client B modifies it
> first. Client A will then see the new value of the column and compose
> a new transaction based on the new contents written by client B."

2 - Compare the revision_number from the Neutron update against what
is presently stored in the OVN database. If the version in the OVN
database is already higher than the version in the update, [abort the
transaction][8]. Here's a pseudo scenario where two concurrent updates
are committed in the wrong order and how the solution above will deal
with the problem:

```
Neutron worker 1 (NW-1): Updates port A with address X (revision_number: 2)

Neutron worker 2 (NW-2): Updates port A with address Y (revision_number: 3)

TRANSACTION 1: NW-2 transaction is committed first and the OVN resource
now has revision_number 3 in it's external_ids column

TRANSACTION 2: NW-1 transaction detects the change in the external_ids
column and is restarted

TRANSACTION 2: NW-1 the OVSDB command now sees that the OVN resource
is at revision_number 3, which is higher than the update version
(revision_number 2) and aborts the transaction.
```

### 3. Detecting inconsistent resources

When things are working as expected the two items above should ensure
that the Neutron and OVN databases are in a consistent state but, what
happens when things go bad ? For example, if the connectivity with the
OVN database is temporarily lost, new updates will start to fail and as
stated in [problem 2](#problem-2-backend-failures) rolling back those
changes in the Neutron database is not always a good idea.

Before this solution we used to maintain a [script][9] that would scan
both databases and fix all the inconsistencies between them but, depending
on the size of the deployment that operation can be very slow. We needed
a better way.

The solution for the detection problem was to create an additional table
in the Neutron database (called "ovn_revision_numbers") with a schema
that look like this:

Column name      |  Type    |  Description
---------------- | -------- | ------------
standard_attr_id | Integer  | Primary key. The reference ID from the standardattributes table in Neutron for that resource. ONDELETE SET NULL.
resource_type    | String   | Primary key. The type of the resource (e.g, ports, routers, ...)
resource_uuid    | String   | The UUID of the resource
revision_number  | Integer  | The version of the object present in OVN
acquired_at      | DateTime | The time that the entry was create. For troubleshooting purposes
updated_at       | DateTime | The time that the entry was updated. For troubleshooting purposes

This table would serve as a "cache" for the revision numbers correspondent
to the OVN resources in the Neutron database.

For the different operations: Create, update and delete; this table will
be used as:

#### Create operation

Neutron has a concept of "precommit" and "postcommit" hooks for the
drivers to implement when dealing with its resources. Basically, the
precommit hook is invoked mid-operation when the Neutron's database
transaction hasn't being committed yet. Also important, the context passed
to the precommit hook will contain a session to the active transaction
which drivers can use to make other changes to the database that will
be part of the same commit. In the postcommit hook, the data is already
fully persisted in Neutron's database and this is where drivers are
suppose to translate the changes to the SDN backend.

Now, to detect inconsistencies of a newly created resource, a new
entry in the ovn_revision_numbers table will be created using the
precommit hook for that resource and the same database transaction. The
revision_number column for the new entry will have a placeholder value
(we use -1) until the resource is successfully created in the OVN database
(in the postcommit hook) and then the revision_number is bumped. If a
resource fails to be created in OVN, the revision_number column in the
ovn_revision_numbers table for that resource will still be set to -1
(the placeholder value) which is [different][10] than it's correspondent
entry in the standardattributes table (which is updated as part of the
Neutron's database transaction).

By looking at the differences in the revision_number's on both tables
is how inconsistencies are detected in the system.

The pseudo code for the create operation looks like this:

```
def create_port_precommit(context, port):
    create_initial_revision(port['id'], revision_number=-1,
                            session=context.session)

def create_port_postcommit(port):
    create_port_in_ovn(port)
    bump_revision(port['id'], revision_number=port['revision_number'])
```

#### Update operation

Every time an update to a resource is successfully committed in
the OVN database, the revision_number for that resource in the
ovn_revision_numbers table will be bumped to match the revision_number
in the standardattributes table. That way if something fails on the OVN
side, the revision_number's from these two tables will be [different][10]
and inconsistencies will be detect in the same way as they are in the
[create operation](#create-operation).

The pseudo code for the delete operation looks like this:

```
def update_port_postcommit(port):
    update_port_in_ovn(port)
    bump_revision(port['id'], revision_number=port['revision_number'])
```

#### Delete operation

The standard_attr_id column in the ovn_revision_numbers table is a
foreign key constraint with a ONDELETE=SET NULL set. Which means that,
upon Neutron deleting a resource the standard_attr_id column in the
ovn_revision_numbers table will be set to NULL.

If deleting a resource succeeds in Neutron but fails in OVN, the
inconsistency can be detect by looking at all resources where the
standard_attr_id column [equals to NULL][11].

When the deletion succeeds in both databases the entry in the
ovn_revision_numbers table can then be delete as well.

The pseudo code for the delete operation looks like this:

```
def delete_port_postcommit(ctx, port):
    delete_port_in_ovn(port)
    delete_revision(port['id'])
```

### 4. Fixing inconsistent resources

Now that the algorithm to detected inconsistencies has been optimized
we were able to create a [maintenance task][12] that runs periodically
(every 5 minutes) and is responsible for detecting and fixing any
inconsistencies it may find in the system.

It's important to note that only one instance of this maintenance task
will be actively running in the whole cluster at a time, all other
instances will be in standby mode (active-standby HA). To achieve that,
each maintenance task instance will attempt to acquire an [OVSDB named
lock][13] and only the instance that currently [holds the lock][14]
will make active changes to the system.

The maintenance task operation is composed by two steps:

1. Detect and fix resources that failed to be created or updated
2. Detect and fix resources that failed to be deleted

Resources that failed to be created or updated will have their
standard_attr_id column pointing to the numerical id of its counterpart
in the standardattributes table but, their revision_number column will
be different.

When inconsistent resources like that are found, the maintenance task will
first try to fetch that resource from the OVN database and; if found, the
resource is updated to what is latest in the Neutron database and then
have their revision_number bumped in the ovn_revision_numbers table. If
the resource is not found, it will be first created in OVN and upon
success its revision_number will be bumped in the ovn_revision_numbers
table.

Resources that failed to be deleted will have their standard_attr_id
column [set to NULL][11]. To fix this type of inconsistency, the
maintenance task will try to fetch the resource from the OVN database
and; if found, the resource and its entry in the ovn_revision_numbers
are deleted. If not found, only the entry in the ovn_revision_numbers
is deleted.

Note that, [the order in which the resources are fixed][15] is
important. When fixing creations and updates the maintenance task will
start fixing the root resources (networks, security groups, etc...) and
leave the leaf ones to the end (ports, floating ips, security group rules,
etc...). That's because, say a network and a port (that belongs to that
network) failed to be created, if it tries to create the port prior to
creating the network that operation will fail again and it will only
be fixed on the next iteration of the maintenance task. The order also
matters for deletion but in the opposite direction, it's preferable to
delete the leaf resources before the root ones to avoid any conflict.

## Conclusion and other notes

This was a long post but I hope it will make it easier for people to
understand with a certain level of detail how [networking-ovn][1] is
dealing with this problem.

Also, In the [OpenStack PTG][16] for the Rocky cycle other Neutron
driver developers were interested in implementing this approach for
their own drivers. It was then decided to attempt to make this approach
more generic[^2] and migrate the code to the Neutron's core repository so
drivers can consume it and avoid duplication. The specification proposing
this change in Neutron can be found [here][17].

[^1]:
    Take a look at the [OVN architecture][3] for more information about
    the Northbound and Southbound databases in OVN

[^2]:
    For example, by removing the dependency on things like the [OVSDB
    named locks][13]. Please check the [proposed specification][17]
    for Neutron.

[0]: https://docs.openstack.org/neutron/latest/
[1]: https://docs.openstack.org/networking-ovn/latest/
[2]: https://bugs.launchpad.net/networking-ovn/+bug/1605089
[3]: http://www.openvswitch.org//support/dist-docs/ovn-architecture.7.html
[4]: https://en.wikipedia.org/wiki/Compare-and-swap
[5]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/ovsdb/commands.py#L1023
[6]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/ovsdb/commands.py#L1092
[7]: https://github.com/openvswitch/ovs/blob/3728b3b0316b44d1f9181be115b63ea85ff5883c/python/ovs/db/idl.py#L1014-L1055
[8]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/ovsdb/commands.py#L1088-L1090
[9]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/ovn_db_sync.py
[10]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/db/maintenance.py#L24
[11]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/db/maintenance.py#L45
[12]: https://github.com/openstack/networking-ovn/blob/master/networking_ovn/common/maintenance.py#L85
[13]: https://tools.ietf.org/html/rfc7047#section-4.1.8
[14]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/common/maintenance.py#L218-L221
[15]: https://github.com/openstack/networking-ovn/blob/4a5b0564de38d0d43d821dc8d8d21faba9589a8d/networking_ovn/common/constants.py#L107-L125
[16]: https://www.openstack.org/ptg/
[17]: https://review.openstack.org/#/c/565463

*[AKA]: Also Known As
*[SDN]: Software-Defined Networking
*[VM]: Virtual Machine
*[OVN]: Open Virtual Network
*[OVSDB]: Open vSwitch Database
*[PTG]: Project Teams Gathering
