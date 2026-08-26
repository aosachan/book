# Bundled runtime provenance

The `runtime` folder is a private, relocatable runtime for this app. It does not add Python to PATH, create file associations, or install the Python launcher.

- CPython: 3.12.10, 64-bit
- Source: signed Python Software Foundation Windows MSI components from `https://www.python.org/ftp/python/3.12.10/amd64/`
- Components: `core.msi`, `exe.msi`, `lib.msi`, `tcltk.msi`, `pip.msi`
- Authenticode: all five components reported `Valid`, signer `Python Software Foundation`
- Pillow: 12.3.0

SHA-256 values recorded during assembly:

```text
core.msi   0075FE3C252B2AF487443A7FBF666C8055E2D111CE7A75DE7DF0A5D45EFB8794
exe.msi    64BEF9BFC893CCE8C697020FD4564A4E62C7F06E8F4B8AC3C5DFEC37BDC56458
lib.msi    699B862A3A0330114F8DDAE9B92E394B4EE93341BA90E19710982CAE62CD4079
tcltk.msi  55C96FFAD69B1C834AA52E11B9CE41637A178BA6AD6607E83956044834276E2A
pip.msi    C508F2CBC48506A8EF518CB792C384BFA3634BEAE65CBFB2CF5F2A4EC1FCA157
```

`runtime/LICENSE.txt` contains the CPython license. Pillow package license metadata is present under `runtime/Lib/site-packages/pillow-12.3.0.dist-info/licenses/`.

The small `tcl/tcl8.6/init.tcl` bootstrap sources the upstream body in `init_full.tcl` after deriving the portable library directory from its own file location. No system Tcl/Tk is used.

