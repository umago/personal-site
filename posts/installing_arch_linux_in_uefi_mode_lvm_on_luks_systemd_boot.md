title: Installing Arch Linux in UEFI mode + LVM on LUKS + systemd-boot
date: 10-09-2016

I've been a Fedora user for a couple of years now (~5 years, before
joining Red Hat) and all my machines run on it. But, I just recently
got a new laptop and decided to give Arch Linux a go. There's no major
reason for the change, I just wanted to try something different and was
specifically looking for a rolling-release distribution[^1].

The [Arch Wiki][0] is fantastic and so is the [installion guide][1] but,
it can be a lot of reading[^2] specially if you deviate from the standard
install instructions. To speed up things a little I created video that
goes through the full process of installing Arch Linux in UEFI mode,
full disk encryption (LVM on LUKS) and systemd-boot as the bootloader.

<div class="video">
    <iframe src="http://www.youtube.com/embed/a1AXHpog9iI" frameborder="0" allowfullscreen></iframe>
</div>

Note that these instructions are just a high level overview of the process
and are not supposed to go into detail of each of the steps. To know
more about each command and the pros and cons of methods/technologies
used in the video please check the [Arch Wiki][0].

[0]: https://wiki.archlinux.org
[1]: https://wiki.archlinux.org/index.php/Installation_guide

[^1]:
    Yes, rawhide does amount to a rolling-release distro but it's just
    a work-in-progress stage for the upcoming stable release.
[^2]:
    It's totally worth it tho!

*[UEFI]: Unified Extensible Firmware Interface
*[LVM]: Logical Volume Manager
*[LUKS]: Linux Unified Key Setup
