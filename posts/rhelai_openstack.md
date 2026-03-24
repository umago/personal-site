title: RHEL AI on OpenStack
date: 11-02-2025
headline: A short guide explaining how to set up and run RHEL AI on OpenStack using a single GPU machine for testing purposes.

In this post, I’ll show you how to deploy [RHEL AI][0] on [OpenStack][3] on a
standalone machine with a GPU.

As of this writing, RHEL AI version 1.3
[does not yet officially support running on OpenStack][1], so consider
this an experimental setup.

## What is RHEL AI ?

If you're new to it, [RHEL AI][0] is an open-source platform designed for
developing, testing, and running AI models. It includes pre-configured
tools and hardware acceleration support, making it easy for someone to
get started with AI, experiment, and integrate it into various operations.

## RHOSO (Red Hat OpenStack Services on OpenShift)

With [RHOSO][2], we are able to run [OpenStack][3] on top of
OpenShift. The control plane is hosted and managed as a workload on
OpenShift meaning that [OpenStack][3] services such as Nova, Keystone,
Neutron, etc... will be installed as operators and deployed as pods.

The [RHOSO][2] data plane is made up of external nodes that runs the
[OpenStack][3] workloads, we refer to those as EDPM (External Data Plane
Management) nodes.

## My setup

For my experiment, I’ll be running RHEL 9.4 on a machine with these
specifications:

* GPU: NVIDIA Corporation AD104GL [L4]
* CPU: Intel(R) Xeon(R) Gold 6348 CPU @ 2.60GHz
* Memory: 250 GiB
* Disk: 1 TiB

## Our experiment

In order to test [RHEL AI][0] on [OpenStack][3] on a single machine,
we will deploy the OpenStack control plane inside a VM using [CRC][4]
and the EDPM node will also run as a VM utilizing PCI passthrough to
pass the NVIDIA GPU to the Nova compute service. Finally, [RHEL AI][0]
will run as an [OpenStack][3] instance on the EDPM node.

This setup will face significant performance issues due to double nested
virtualization. It's clearly not intended for real-world use, just as
an experiment to see if everything works as expected.

## Setting up the host

To setup the host we need to enable virtualization and IOMMU (Input-Output
Memory Management Unit), blacklist the graphics card in the host machine
and reserve the GPU via VFIO (Virtual Function I/O) so the VM can use it.

Each of these steps are described below:

### Enable virtualization

To use PCI passthrough, first we need to ensure that virtualization is
enabled in the BIOS. Enabling virtualization differs by vendor, so be
sure to check their documentation. For Intel, this feature is called VT-d,
while for AMD, it's referred to as AMD-V.

### Blacklist the drivers

To ensure the graphics drivers are not loaded in the host we need to
blacklist them. Depending on vendor of the card it will be a different
driver name, for example:

* For NVIDIA GPUs:

``` bash
echo -e "blacklist nouveau\nblacklist nvidia*" | tee -a /etc/modprobe.d/blacklist.conf
```

* For AMD GPUs:

``` bash
echo -e "blacklist amdgpu\nblacklist radeon" | tee -a /etc/modprobe.d/blacklist.conf
```

### Enable IOMMU

IOMMU is a feature that controls how devices access memory, improving
performance and security in virtual environments.

In order to enable IOMMU we need to change the kernel command line.
If you are using intel like me, you can run the following command to
update the kernel command line in the bootloader (assuming GRUB bootloader
is being used):

``` bash
grubby --update-kernel ALL --args 'intel_iommu=on iommu=pt'
```

For AMD, it should be enabled by default so you can skip this step.

### Reserve the GPU

To reserve the GPU and give the VM directly access to the PCI device we will
use a feature in the Linux kernel called VFIO.

Just like IOMMU, VFIO is configured via the kernel command line. But first,
we need to find the **product ID** and **vendor ID** o a system with the
GPU device installed:

``` bash
# lspci -nn | grep NVIDIA
4b:00.0 3D controller [0302]: NVIDIA Corporation AD104GL [L4] [10de:27b8] (rev a1)
```

In the example above, the vendor ID is **10de** and the product ID
is **27b8**.  Now, let's update the kernel command line in the bootloader:

``` bash
PCI="10de:27b8"
sudo grubby --update-kernel ALL --args "rd.driver.pre=vfio_pci vfio_pci.ids=${PCI} modules-load=vfio,vfio-pci,vfio_iommu_type1,vfio_pci_vfio_virqfd"
```

Once that's done, reboot the machine.

## Deploying RHOSO

To deploy RHOSO, we'll use some helper scripts developed by my team at Red Hat.

The deployment has two phases:
1. Deploying the control plane
2. Deploying the EDPM node

But first, let's download the scripts, install the dependencies and validate
our host machine:

``` bash
git clone https://github.com/openstack-k8s-operators/rhoso-rhelai/
cd ./rhoso-rhelai/nested-passthrough/
```

Note, the latest commit ID at the time of writing is: 582b22229c313fe5fc55e8ae820e872a464681d0

To install the required dependencies and tools run:

``` bash
make download_tools
```

Now, let's verify our host machine to ensure the previous steps were
applied correctly:

``` bash
make validate_host
```

If everything is set up correctly, you should see an output like this:

``` bash
$ make validate_host
✔ IOMMU correctly configured
✔ NVIDIA GPU found
✔ GPU held by vfio-pci: 4b:00.0
```

### Deploying the control plane

To deploy the control plane, first we need a pull-secret from the
[OpenShift website][5]. This file should be located at **~/pull-secret**.

Once the **~/pull-secret** file is created, run the following command:

``` bash
make deploy_controlplane
```

After the command completes, you now should have a single-node OpenShift
cluster with the [OpenStack][3] services running on it. For example:

``` bash
$ eval $(crc oc-env)
$ oc get pods | grep nova-api
nova-api-0                             2/2     Running     0          3m23s
nova-api-c3c5-account-create-9vw8t     0/1     Completed   0          5m7s
nova-api-db-create-662w9               0/1     Completed   0          5m17s
```

### Deploying the EDPM node

We now need to deploy the EDPM node, this is will be a VM where the
[RHEL AI][0] instance will run on.

``` bash
make deploy_edpm
```

Note, you can adjust the size of the disk, memory and number of CPUs of the
EDPM node using the **EDPM_DISK**, **EDPM_RAM** and **EDPM_CPUS** environment
variables.

Once deployed, the IP of the EDPM node will be **192.168.122.100**,
let's SSH into the node and verify that our GPU is being passed to it:

``` bash
$ ssh -i ~/rhoso-rhelai/nested-passthrough/out/ansibleee-ssh-key-id_rsa root@192.168.122.100
[root@edpm-compute-0 ~]# lspci -d "10de:"
06:00.0 3D controller: NVIDIA Corporation AD104GL [L4] (rev a1)
```

## Deploying RHEL AI

In order to deploy the [RHEL AI][0] instance, first create a download
link in the [RHEL AI download page][6]. Then, copy the link for the
qcow2 format corresponding to your GPU vendor and assign it to the
**AI_IMAGE_URL** environment variable or, you can download the image
locally and save it as **out/rhel-ai-disk.qcow2**.

Note, you may need to join the [RHEL AI trial][7] first.

``` bash
AI_DISK=300 AI_IMAGE_URL="https://access.cdn.redhat.com/..." make deploy_rhel_ai
```

Note, I adjusted the disk size via the **AI_DISK** environment variable to
fit my deployment. However, if you plan to experiment with multiple models,
I recommend using at least 800 GiB.

After running make deploy_rhel_ai, you should see a message similar to the
one below:

> Access VM with: oc rsh openstackclient ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i ./rhel-ai.pem cloud-user@192.168.122.222

We can now access the [RHEL AI][0] instance to check if the system detects
the GPU and if the vendor driver recognizes the device:

``` bash
$ oc rsh openstackclient ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i ./rhel-ai.pem cloud-user@192.168.122.222
[cloud-user@rhel-ai ~]$ lspci -d "10de:"
05:00.0 3D controller: NVIDIA Corporation AD104GL [L4] (rev a1)
[cloud-user@rhel-ai ~]$ nvidia-smi -L
GPU 0: NVIDIA L4 (UUID: GPU-de84ad31-ebe4-fc2d-5518-4b13a4c16e1c)
```
## What’s Next?

In this blog post we covered the essential steps to get [RHEL AI][0]
deployed on [OpenStack][3] but, it does not stop there. If you want to
continue exploring [RHEL AI][0] and [InstructLab][8], take a look at the
[official documentation][9]. There, you will find instructions on setting
up [InstructLab][8], as well as downloading, chatting with, and serving
various AI models.

Thanks for reading! Happy experimenting with [RHEL AI][0] on [OpenStack][3]!

<a href=/posts/images/rhelai_openstack.png target="_blank">
<img src=/posts/images/rhelai_openstack.png width=70% class="center" title="RHEL AI on OpenStack">
</a>

[0]: https://developers.redhat.com/products/rhel-ai/overview
[1]: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux_ai/1.3/html/getting_started/hardware_requirements_rhelai#hardware_req_training
[2]: https://docs.redhat.com/en/documentation/red_hat_openstack_services_on_openshift/18.0/html/planning_your_deployment/assembly_red-hat-openstack-services-on-openshift-overview
[3]: https://www.openstack.org/
[4]: https://crc.dev/docs/introducing/
[5]: https://cloud.redhat.com/openshift/create/local
[6]: https://access.redhat.com/downloads/content/932
[7]: https://www.redhat.com/en/technologies/linux-platforms/enterprise-linux/ai/trial
[8]: https://instructlab.ai/
[9]: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux_ai/1.3/html/building_your_rhel_ai_environment/index

*[VM]: Virtual Machine
*[EDPM]: External Data Plane Management
*[IOMMU]: Input-Output Memory Management Unit
*[VFIO]: Virtual Function I/O
*[GRUB]: GRand Unified Bootloader
