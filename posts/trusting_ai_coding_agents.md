title: Trusting AI Coding Agents (With a Sandbox)
date: 26-03-2026
headline: A lightweight approach to using AI coding agents while keeping my system secure.

I've been using [Goose][0] as my AI coding agent since it supports
multiple LLM providers. That's been useful because my company offers
both a Claude Code CLI and a Gemini CLI, while I also use OpenRouter for
personal projects. [Goose][0] lets me integrate with all these tools in
one place and avoid vendor lock-in.

But one thing that I've been missing is a sandbox that works across all
these agents. Sometimes it's useful to let an agent have more freedom to
design, experiment, and implement systems, but that also means carefully
controlling [what it can access][1].

Right now, each tool handles isolation differently (or none at all) and I
would need to trust all implementations are both correct and secure. Plus,
**supply chain attacks are real**; I'm writing this while the [LiteLLM
incident][2] is unfolding. This stuff happens all the time.

As I started looking into this, I noticed Anthropic uses [Bubblewrap][3]
on Linux for their [sandbox implementation][4] in Claude Code. Bubblewrap
is a great choice because it's lightweight and is built on Linux Kernel
features like namespaces and seccomp. It's also used in other larger
applications such as [Flatpak][5].

## What Bubblewrap Does (Simplified)

The command below creates a minimal Bubblewrap sandbox with write access
only in the current folder:

```bash
$ bwrap \
    --ro-bind /usr /usr \
    --ro-bind /bin /bin \
    --ro-bind /lib /lib \
    --ro-bind /lib64 /lib64 \
    --bind "$PWD" "$PWD" \
    --tmpfs /tmp \
    --unshare-all \
    --die-with-parent \
    /usr/bin/bash
```

- **/usr** **/bin**, **/lib**, **/lib64**: Minimal system files so your shell and commands work.
- **$PWD**: Your current folder is readable and writable.
- **/tmp**:  Isolated temporary storage inside the sandbox.
- **--unshare-all**: Isolates namespaces (PID, mount, network, etc...).
- **--die-with-parent**: Sandbox exits automatically when you kill bash.

You can try:

```bash
bash-5.3$ ping www.google.com
ping: socktype: SOCK_RAW
ping: socket: Operation not permitted
ping: => missing cap_net_raw+p capability or setuid?
bash-5.3$ echo "oops" > /usr/try.txt
bash: /usr/try.txt: Read-only file system
bash-5.3$ ls /etc
ls: cannot access '/etc': No such file or directory
bash-5.3$ pwd
/home/lucas/Projects/foo-project
bash-5.3$ echo "foobar" > foobar
bash-5.3$ cat foobar
foobar
```

As you can see, you can read and write files in your current folder
and run programs from /bin and /usr (read-only). Everything else, like
system config files and other folders, is hidden. Your commands work,
but only inside this sandboxed space.

## Sanboxing vs Containers

It's important to say that this does not replace things like Podman or
Docker, they solve different problems. With containers you need things
like images, daemons, volume mounts, etc.. Bubblewrap works with the
environment you already have and just restricts what a process can access,
it's fast and simple.

In fact, you can run Bubblewrap inside a container, adding an extra
layer of security on top of the container's existing protections.

## My Current Solution

I wanted something more than a bash script wrapped around [Bubblewrap][3],
something I could configure and extend more easily before it became a
mess. So I built a small CLI in Go: [bwai (or bubblewrap-ai)][6].

The idea is simple. Just cd into the project you want the agent to work
on and run **bwai**:

```bash
$ cd ~/Projects/foo-project
$ bwai
bwai: sandboxed in /home/lucas/Projects/foo-project
[🫧] > goose
```

When you see the "[🫧]" prompt, you're in the sandbox. From there
you can launch an agent as you normally would (only tested with goose,
claude and gemini). If you want to skip the shell part, you can pass
the command directly:

```bash
$ bwai -c claude
```

It works out of the box with no config file. But if you want to customise
things like, which dotfiles the agent can read, which environment
variables to passthrough, or which command to launch by default, you can
create a **~/.bwai.json** in your home directory (run **bwai --dump-config**
to get the full defaults as a starting point).

The tool gives you a fine-grained layer of control:

- Your current folder is fully writable, so the agent can work on the project files (that's the point!).
- System binaries and libraries are read-only. The agent can run commands but can't modify critical parts of the system.
- All other parts of the system, including config files, other folders, and critical paths, are off-limits.

Still in the early stages, and I'll be experimenting with it more over
the next days, but it already does what I need for now. If you want to try
it out, the [project README][6] has everything you need to get started.

[0]: https://block.github.io/goose/
[1]: https://code.claude.com/docs/en/permission-modes#skip-all-checks-with-bypasspermissions-mode
[2]: https://docs.litellm.ai/blog/security-update-march-2026
[3]: https://github.com/containers/bubblewrap
[4]: https://code.claude.com/docs/en/sandboxing
[5]: https://flatpak.org
[6]: https://github.com/umago/bubblewrap-ai/
