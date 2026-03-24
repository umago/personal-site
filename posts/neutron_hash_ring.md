title: Neutron Distributed OVSDB events handler (Hash Ring)
date: 15-11-2024
headline: Distributing Neutron workloads across workers using a Consistent Hash Ring for scalable task processing.

In this post I will talk about a bottleneck problem handling OVSDB events that
we had in the ML2/OVN driver for [OpenStack Neutron][0] and how we solved it.

## Problem description

In the ML2/OVN driver, the OVSDB Monitor class is responsible for
listening to the OVSDB events and performing certain actions on the
them. We use it extensively for various tasks including critical ones
such as monitoring for port binding events (in order to notify [Neutron][0]
or [Nova][1] that a port has been bound to a given chassis). This OVSDB
Monitor class used a distributed OVSDB lock to ensure that only a single
worker was active and handling these events at a time.

This approach, while effective during periods of low activity, became
a bottleneck with ports taking a long time to transition to active when
the cluster experienced high demand. Also, In the event of a failover,
all events would be lost until a new worker became active.

<a href=/posts/images/neutron_hash_ring_problem_diagram.png target="_blank">
<img src=/posts/images/neutron_hash_ring_problem_diagram.png width=70% class="center" title="Neutron Hash Ring Problem Diagram">
</a>

## Distributed OVSDB events handler

In order to fix this problem, it was proposed using a [Consistent Hash
Ring][2] to distribute the load of handling events across multiple
workers.

A new table called ovn_hash_ring was created in the Neutron Database
where the Neutron Workers capable of handling OVSDB events will be
registered. The table contains the following columns:

Column name  |  Type    |  Description
------------ | -------- | ------------
node_uuid    | String   | Primary key. The unique identification of a Neutron Worker.
hostname     | String   | The hostname of the machine this Node is running on.
created_at   | DateTime | The time that the entry was created. For troubleshooting purposes.
updated_at   | DateTime | The time that the entry was updated. Used as a heartbeat to indicate that the Node is still alive.

This table is used to form the [Consistent Hash Ring][2]. Fortunately,
a implementation already exists in a library called [tooz][3] for
OpenStack. It was contributed by the [OpenStack Ironic][4] team which
also uses this data structure in order to spread the API request load
across multiple Ironic Conductors.

Here's an example of how a [Consistent Hash Ring][2] works using [tooz][3]:

```
from tooz import hashring

hring = hashring.HashRing({'worker1', 'worker2', 'worker3'})

# Returns set(['worker3'])
hring[b'event-id-1']

# Returns set(['worker1'])
hring[b'event-id-2']
```

### How OVSDB Monitor will use the new Hash Ring data structure

Every instance of the OVSDB Monitor class will register itself in
the database and start listening to the events coming from the OVSDB
database.  Each OVSDB Monitor instance have a unique ID that is part of
the [Consistent Hash Ring][2].

When an event arrives, each OVSDB Monitor instance will hash the event
UUID against the hash ring which will return one OVSDB Monitor instance
ID. If this ID matches with the instance own ID then that instance will
the one that process the event.

<a href=/posts/images/neutron_hash_ring_solution_diagram.png target="_blank">
<img src=/posts/images/neutron_hash_ring_solution_diagram.png width=70% class="center" title="Neutron Hash Ring Solution Diagram">
</a>

In the image above, colors are used to illustrate the change from a
one-to-one relationship between Controllers and Workers in ACTIVE-STANDBY
mode that we had before to a more scalable configuration with the Hash
Ring where each Controller can now host multiple Workers in ACTIVE-ACTIVE
mode.

## Benchmarking the new changes

To assess the improvements from using the Hash Ring we used a performance
analysis tool for OpenStack called [Browbeat][5]. We also created a new
[scenario][6] for [Browbeat][5] that would take [OpenStack Nova][1] out of
the picture and simulates a VM on the available hypervisors by creating
a network namespace and attaching a port to the OVS bridge. This enabled
us to simulate numerous VMs booting concurrently without requiring the
resources to host them all.

In addition to comparing the OVSDB Monitor class with and without the
[Consistent Hash Ring][2], we also tested ML2/OVN against ML2/OVS,
which was the default driver in [OpenStack Neutron][0] at the time.

With a concurrency set to 25 and a total of 150 VMs being provisioned,
the comparison between ML2/OVN and ML2/OVS **BEFORE** the introduction
of the distributed OVSDB event handler looked like this:

<a href=/posts/images/neutron_hash_ring_before_ovs_c_25_t_150.png target="_blank">
<img src=/posts/images/neutron_hash_ring_before_ovs_c_25_t_150.png width=70% class="center" title="Before: ML2/OVN vs ML2/OVS (Concurrency:25, Total:150)">
</a>

The average wait time for a ML2/OVN port to become active was 45.7
seconds, whereas in ML2/OVS, it was only 3.7 seconds. However, in ML2/OVS,
it took an average of 43.6 seconds for a VM to respond to a ping, while in
ML2/OVN, it was only 5.7 seconds. Overall, the two drivers were similar,
with ML2/OVS being slightly faster.

Using the same 25 concurrency and 150 total VMs being provisioned,
this is what ML2/OVN in comparison with ML2/OVS looked like with the
distributed OVSDB event handler:

<a href=/posts/images/neutron_hash_ring_after_ovs_c_25_t_150.png target="_blank">
<img src=/posts/images/neutron_hash_ring_after_ovs_c_25_t_150.png width=70% class="center" title="After: ML2/OVN vs ML2/OVS (Concurrency:25, Total:150)">
</a>

The time it took for ports to become active in ML2/OVN dropped to 2
seconds (from an average of 45.7 seconds) and the average time it took
for a VM to respond to a ping was 8.5 seconds. That's an impressive
improvement, with the distributed event handler a port only takes a
fraction (4.4%) of the original time to become active!

Here's is the ML2/OVN numbers side-by-side:

<a href=/posts/images/neutron_hash_ring_before_after_ovn_c_25_t_150.png target="_blank">
<img src=/posts/images/neutron_hash_ring_before_after_ovn_c_25_t_150.png width=70% class="center" title="ML2/OVN comparison (Concurrency:25, Total:150)">
</a>

This difference becomes even more apparent when we increase the
concurrency to 50 (up from 25). Here’s how the numbers look:

<a href=/posts/images/neutron_hash_ring_before_after_ovn_c_50_t_150.png target="_blank">
<img src=/posts/images/neutron_hash_ring_before_after_ovn_c_50_t_150.png width=70% class="center" title="AML2/OVN comparison (Concurrency:50, Total:150)">
</a>

Now the average time for a port to become active dropped from 94.6 seconds
to only 3 seconds. Note that it took longer for the port to respond to a
ping on average with the new approach, that's because [ovn-controller][7]
will now install more flows per second, putting more pressure on [Open
vSwitch daemon][8] (running on the compute nodes) and this is observed
through its CPU utilization.

Before, without the distributed event handler:
<a href=/posts/images/neutron_hash_ring_before_openvswitch_compute_0.png target="_blank">
<img src=/posts/images/neutron_hash_ring_before_openvswitch_compute_0.png width=70% class="center" title="Before: OpenVSwitch Compute-0 CPU Utilization (Concurrency:50, Total:150)">
</a>

After, with the distributed event handler:
<a href=/posts/images/neutron_hash_ring_after_openvswitch_compute_0.png target="_blank">
<img src=/posts/images/neutron_hash_ring_after_openvswitch_compute_0.png width=70% class="center" title="After: OpenVSwitch Compute-0 CPU Utilization (Concurrency:50, Total:150)">
</a>

### Final observations

* [ovn-controller][7] will now install more flows per second, putting more
  pressure on [Open vSwitch daemon][8] (running on the compute nodes) and
  this is observed through its CPU utilization.
* Events are now processed in a distributed manner across the cloud. CPU
  consumption is spread across the controllers, rather than being concentrated
  on just one.
* At the time this work was done [ovn-controller][7] was just a single-threaded
  loop that calculates everything on each iteration every time some change
  happens. As events are now processed in parallel by all the Neutron workers,
  [ovn-controller][7] (on the compute nodes) will process more changes per
  iteration so its overall CPU consumption is also lowered.
* Control plane convergence in ML2/OVN is now significantly faster.

## Issues encountered during this work

* [Hash Ring race condition during workers initialization](https://bugs.launchpad.net/networking-ovn/+bug/1833105)
* [OVN metadata: Race condition (Metadata service is not ready for port)](https://bugs.launchpad.net/networking-ovn/+bug/1831224)
* [OVN metadata: Leftovers namespaces in the environment](https://bugs.launchpad.net/networking-ovn/+bug/1832003)
* [Core OVN: Incremental processing memory leak and performance issues](https://mail.openvswitch.org/pipermail/ovs-discuss/2019-June/048822.html)
* [ML2/OVS: DVR FIP traffic not working](https://bugzilla.redhat.com/show_bug.cgi?id=1720166)

## References

* [The upstream spec file for this work](https://docs.openstack.org/neutron/latest/contributor/internals/ovn/distributed_ovsdb_events.html)
    - Here you can find more details about the implementation that is not
      part of this blog post. Things such as heartbeating, clean up, etc...
* The two main patches containng the implementation in networking-ovn (this work was prior to ML2/OVN migrate to the main Neutron repository):
    - <https://review.opendev.org/c/openstack/networking-ovn/+/655407>
    - <https://review.opendev.org/c/openstack/networking-ovn/+/655408>

[0]: https://docs.openstack.org/neutron/latest/
[1]: https://docs.openstack.org/nova/latest/
[2]: https://en.wikipedia.org/wiki/Consistent_hashing
[3]: https://docs.openstack.org/tooz/latest/
[4]: https://docs.openstack.org/ironic/latest/
[5]: https://github.com/cloud-bulldozer/browbeat
[6]: https://github.com/danalsan/browbeat/commit/0ff72da52ddf17aa9f7269f191eebd890899bdad
[7]: https://www.ovn.org/support/dist-docs/ovn-controller.8.txt
[8]: http://www.openvswitch.org/support/dist-docs/ovs-vswitchd.8.html

*[OVN]: Open Virtual Network
*[VM]: Virtual Machine
*[VMs]: Virtual Machines
*[hypervisors]: A software that you can use to run multiple virtual machines on a single physical machine
