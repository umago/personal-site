title: OVN: Transport Zones
date: 14-05-2019

In this post, I present a new feature that recently landed in [OVN][0]
called Transport Zones (AKA TZs).

The patch implementing it can be found [here][2].

## Problem description

With the recent interest in [Edge Computing][1], we've started evaluating
the current situation of [OVN][0] for the task.

One of problems identified was that [OVN][0] always created a mesh of
tunnels between every Chassis in the cloud and in the [Edge Computing][1]
case, nodes in an edge site should not be able to communicate with nodes in
every other edge site. In simpler terms, we needed a way to block tunnels
to be formed between "edge-to-edge" while still allowing tunnels between
"edge-to-central".

The most natural solution we thought before was to use firewalls to
block those undesirable tunnels but, that could lead to some unintended
consequences since Chassis would still try to form those tunnels. It
would just fail or timeout over and over again.

That's when we thought about introducing a new feature in [OVN][0] that
would allow users to separate Chassis into different logical groups. And
that's what Transport Zones are about.

## Transport Zones

Transport Zones is a way to enable users to separate Chassis into one
or more logical groups. If not set, Chassis will be considered part of
a default group.

Configuring Transport Zones is done by creating a key called
**ovn-transport-zones** in the *external_ids* column of the *Open_vSwitch*
table from the local OVS instance. The value is a string with the name
of the Transport Zone that this instance is part of. Multiple Transport
Zones can be specified with a comma-separated list. For example:

```
$ sudo ovs-vsctl set open . external-ids:ovn-transport-zones=tz1

OR

$ sudo ovs-vsctl set open . external-ids:ovn-transport-zones=tz1,tz2,tz3
```

Once the configuration is set, the *ovn-controller* will detect those
changes and will update the **transport_zones** column of the Chassis
table in the [OVN Southbound Database][0] with the new data:

```
$ sudo ovn-sbctl list Chassis
_uuid               : 8a48b880-4a00-4ab9-ae3a-2d7ac6b04279
encaps              : [517da462-a8c1-488f-b2e2-f9b7190e77cb]
external_ids        : {datapath-type="", iface-types="erspan,geneve,gre,internal,ip6erspan,ip6gre,lisp,patch,stt,system,tap,vxlan", ovn-bridge-mappings=""}
hostname            : central
name                : central
nb_cfg              : 0
transport_zones     : ["tz1", "tz2", "tz3"]
vtep_logical_switches: []

...
```

And last, by updating the Chassis table, an OVSDB event will generated
which all ovn-contollers will then handle and recalculate its tunnels
based on the new Transport Zones information. Chassis with at least one
common Transport Zone will have a tunnel formed between them.

Tunnels can be checked by running the following command:

```
$ sudo ovs-vsctl find interface type="geneve"
_uuid               : 49f1e715-6cda-423b-a1b2-a8a83e5747e0
admin_state         : up
bfd                 : {}
bfd_status          : {}
cfm_fault           : []
cfm_fault_status    : []
cfm_flap_count      : []
cfm_health          : []
cfm_mpid            : []
cfm_remote_mpids    : []
cfm_remote_opstate  : []
duplex              : []
error               : []
external_ids        : {}
ifindex             : 6
ingress_policing_burst: 0
ingress_policing_rate: 0
lacp_current        : []
link_resets         : 0
link_speed          : []
link_state          : up
lldp                : {}
mac                 : []
mac_in_use          : "96:e4:e4:c7:ee:4c"
mtu                 : []
mtu_request         : []
name                : "ovn-worker-0"
ofport              : 2
ofport_request      : []
options             : {csum="true", key=flow, remote_ip="192.168.50.101"}
other_config        : {}
statistics          : {rx_bytes=0, rx_packets=0, tx_bytes=0, tx_packets=0}
status              : {tunnel_egress_iface="eth1", tunnel_egress_iface_carrier=up}
type                : geneve

...
```

As you can see, everything is dynamic and no restart of services are
required.

### A small experiment

In order to see this feature in action, I'm going to deploy an [OVN][0]
environment using some [Vagrant boxes][3]. I will do it using the commands
provided at Daniel's [blog post][4] as a base for this experiment.

Once the setup of the **ovn-multinode** Vagrant script is finished,
we will have three nodes available:

* Central node: A machine running the *ovsdb-servers* (North and
  Southbound databases), *ovn-northd* and *ovn-controller*.

* Worker1 and Worker2 nodes: Two machines running *ovn-controller*
  connected to Southbound database in the Central node.

To start, let's configure things in a way that a VM running on Worker1
can communicate with another VM running on Worker2.

From the *Central* node, let's create the topology as described in the
[blog post][4]:

```
sudo ovn-nbctl ls-add network1
sudo ovn-nbctl lsp-add network1 vm1
sudo ovn-nbctl lsp-add network1 vm2
sudo ovn-nbctl lsp-set-addresses vm1 "40:44:00:00:00:01 192.168.0.11"
sudo ovn-nbctl lsp-set-addresses vm2 "40:44:00:00:00:02 192.168.0.12"
```

Now, let's log into *Worker1* node and bind "vm1" to it:

```
sudo ovs-vsctl add-port br-int vm1 -- set Interface vm1 type=internal -- set Interface vm1 external_ids:iface-id=vm1
sudo ip netns add vm1
sudo ip link set vm1 netns vm1
sudo ip netns exec vm1 ip link set vm1 address 40:44:00:00:00:01
sudo ip netns exec vm1 ip addr add 192.168.0.11/24 dev vm1
sudo ip netns exec vm1 ip link set vm1 up
```

And "vm2" to the *Worker2* node:

```
sudo ovs-vsctl add-port br-int vm2 -- set Interface vm2 type=internal -- set Interface vm2 external_ids:iface-id=vm2
sudo ip netns add vm2
sudo ip link set vm2 netns vm2
sudo ip netns exec vm2 ip link set vm2 address 40:44:00:00:00:02
sudo ip netns exec vm2 ip addr add 192.168.0.12/24 dev vm2
sudo ip netns exec vm2 ip link set vm2 up
```

Let's ping "vm2" (running on *Worker2*) from "vm1" (running on *Worker1*):

```
$ sudo ip netns exec vm1 ping 192.168.0.12 -c 3
PING 192.168.0.12 (192.168.0.12) 56(84) bytes of data.
64 bytes from 192.168.0.12: icmp_seq=1 ttl=64 time=1.20 ms
64 bytes from 192.168.0.12: icmp_seq=2 ttl=64 time=1.35 ms
64 bytes from 192.168.0.12: icmp_seq=3 ttl=64 time=0.595 ms

--- 192.168.0.12 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2004ms
rtt min/avg/max/mdev = 0.595/1.053/1.355/0.329 ms
```

Great, it works! Let's now configure the Transport Zones following the
rules below:

* The *Central* node should be able to communicate with both *Worker1*
  and *Worker2* nodes.

* *Worker1* and *Worker2* should only be able to communicate with the
  *Central* node. Not between themselves.

For that we need two Transport Zones, which in this examples we are going
to name as "tz1" and "tz2". The *Central* node will be part of both TZs,
*Worker1* will belong only to "tz1" and *Worker2* to "tz2".

From the *Central* node, do:

```
$ sudo ovs-vsctl set open . external-ids:ovn-transport-zones=tz1,tz2
```

From the *Worker1* node, do:

```
$ sudo ovs-vsctl set open . external-ids:ovn-transport-zones=tz1
```

And, from the *Worker2* node, do:

```
$ sudo ovs-vsctl set open . external-ids:ovn-transport-zones=tz2
```

Let's check the tunnels on each node. In the *Central* node we have:

```
$ sudo ovs-vsctl find interface type="geneve" | grep name
name                : "ovn-worker-0"
name                : "ovn-worker-1"
```

*Worker1*:

```
$ sudo ovs-vsctl find interface type="geneve" | grep name
name                : "ovn-centra-0"
```

*Worker2*:

```
$ sudo ovs-vsctl find interface type="geneve" | grep name
name                : "ovn-centra-0"
```

As you can see, the nodes *Worker1* and *Worker2* does not have a tunnel
formed between them. That means that pinging "vm2" (running on *Worker2*)
from "vm1" (running on *Worker1*) should be blocked:

```
$ sudo ip netns exec vm1 ping 192.168.0.12 -c 3
PING 192.168.0.12 (192.168.0.12) 56(84) bytes of data.
^C
--- 192.168.0.12 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 1999ms
```

## OpenStack integration

Our next step now is to integrate the Transport Zones feature with
the OpenStack [networking-ovn][5] ML2 driver to provide for [OVN][0].

## Other use cases

Although created with the [Edge Computing][1] case in mind, this feature
could potentially be used for several other use cases, including but not
limited to:

* Security Zones: Nodes in a more secure zone not being able to
  exchange traffic with a node in a less secure zone.

* Parallel network infrastructure: A way of increasing resiliency in
  large networks by creating a parallel infrastructure. Two different
  networks with separate hardware (perhaps even different vendors to
  protect against vulnerabilities in the network OS). In this case, you
  would also want to prevent East/West traffic between the networks to
  prevent inter-dependency.

[0]: http://www.openvswitch.org/support/dist-docs/ovn-architecture.7.html
[1]: https://en.wikipedia.org/wiki/Edge_computing
[2]: https://mail.openvswitch.org/pipermail/ovs-dev/2019-April/358314.html
[3]: https://github.com/danalsan/vagrants/
[4]: http://dani.foroselectronica.es/multinode-ovn-setup-509/
[5]: https://docs.openstack.org/networking-ovn/latest/
[6]: https://docs.openstack.org/neutron/stein/admin/config-az.html

*[AKA]: Also Known As
*[Chassis]: In OVN terminology, every node where the ovn-controller service is running is referred to as a Chassis.
*[VM]: Virtual Machine
*[TZs]: Transport Zones
