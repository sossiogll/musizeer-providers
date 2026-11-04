# Local storage

Keeps the library in a folder of the machine Musizeer runs on. A storage provider: it stores each downloaded file
under the library folder, plays it from there and lists what is on it.

- **Store** moves the file from the call's workspace into the library, creating the folders it needs, and the file
  appears under its final name **all at once or not at all**: a rename when the workspace and the library are on one
  volume, otherwise (in the sandbox they are two mounts and `rename` fails with `EXDEV`) a copy to a hidden
  `.<name>.part` in the destination folder, flushed to disk and renamed onto the final name, and only then is the
  source removed. A failed copy removes the `.part` file. A music server that scans meanwhile never sees half a file.
- **Stream** puts the library file in the workspace (a hard link, or a copy across volumes) for the host to serve;
  the library is never touched.
- **List** walks the folder; a link to a folder is listed as a file, not followed, so a circular link cannot stall it.
- A path that is absolute, or that climbs out of the folder, is refused: the check is lexical and does not follow
  links, because a library may use them on purpose.

## Settings

| Key | Meaning |
| --- | --- |
| `root_dir` | The library folder, a `folder` setting: you pick one of the root folders declared in Administration and a path inside it (there is no default root, and no default path). Until it is set no download is started and `store` is never called. |

## Permissions

What the sandbox lets it do, and nothing else (the admin sees this before installing):

- **read and write the folder you set in `root_dir`** (the library). The gateway binds that folder into the
  sandbox at the same path, and only if it lies inside a root folder the administrator declared; files it creates
  there belong to the gateway's user, so the folder must be writable by it. Nothing else of the disk is visible.

No network, no raw TCP, no declared resource limits (the gateway's defaults apply).

## Build and test

From the root of the repository (see the top-level [README](../README.md)):

```sh
scripts/test.sh local
scripts/build.sh --registry 127.0.0.1:18800 --catalog-dir /tmp/catalogs local
```
