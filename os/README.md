# GravityNAS OS

GravityNAS OS is a dedicated Raspberry Pi appliance built on Raspberry Pi OS Lite 64-bit for Pi 4. It does not include a desktop environment or a custom kernel. The microSD contains the operating system and application; user data should be placed on a separate USB disk for better capacity and to reduce writes to the boot card.

## Build a bootable image

Image creation uses the upstream `pi-gen` pipeline. Run it on a Debian/Ubuntu
Linux build host with root privileges and network access. Keep the release
signing private key off the NAS and out of the image. The builder defaults to
pi-gen's `arm64` branch; do not switch it to `master`, which builds 32-bit:

```bash
sudo apt update
sudo apt install -y git rsync openssl quilt qemu-user-binfmt debootstrap \
	zerofree zip dosfstools libcap2-bin grep xz-utils file bc \
	libarchive-tools curl xxd kmod gpg pigz arch-test binfmt-support
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out update-private.pem
chmod 0600 update-private.pem
openssl pkey -in update-private.pem -pubout -out update.pub
GRAVITYNAS_UPDATE_PUBLIC_KEY="$PWD/update.pub" sudo -E os/scripts/build-pi-image.sh 1.0.0
```

The builder produces a Raspberry Pi OS Lite Trixie ARM64 image, adds the GravityNAS
service and dependencies, enables SSH with a per-image random `nasadmin`
password, and installs only the public update key. The password is written to
`build/gravitynas-image/credentials.txt` with restrictive permissions. The
image is not flashed automatically. Use Raspberry Pi Imager to write the
`.img.xz` artifact to a microSD card; connect Ethernet for the first boot, then
open `http://gravitynas.local`.

Set `GRAVITYNAS_PI_GEN_REF` to another compatible pi-gen branch, tag, or commit
to select the upstream build input. Set `GRAVITYNAS_IMAGE_OCR=1` to include
Tesseract; OCR is omitted by default to keep the appliance image smaller.

## USB data disk

For NAS files, connect a disk that is already formatted as ext4, then run
`sudo gravitynas-storage /dev/sda1` (replace the device with the correct
partition). The helper mounts by UUID at `/srv/gravitynas-storage`, updates
Samba and systemd, and never formats or erases the disk. If the configured disk
is absent during boot, the NAS service refuses to start rather than filling the
microSD card. The SQLite database and operating system remain on the microSD.

## Install on Raspberry Pi OS Lite

For an already flashed 64-bit Raspberry Pi OS Lite host, run from the project
root:

```bash
GRAVITYNAS_UPDATE_PUBLIC_KEY="$PWD/update.pub" sudo -E os/scripts/install-pi4.sh
```

The installer targets arm64, does not repartition or format disks, creates a
dedicated unprivileged service account, stores application data in
`/var/lib/gravitynas`, and installs the initial code as a versioned release in
`/opt/gravitynas/releases/`. A stable `current` symlink lets updates switch
versions atomically. Set `GRAVITYNAS_INSTALL_OCR=1` before running the script
to install the OCR system packages.

## Signed application updates

Build a release archive on the trusted development machine:

```bash
GRAVITYNAS_SIGNING_KEY="$PWD/update-private.pem" os/scripts/package-release.sh 1.0.1
```

Copy the generated `.tar.gz` and adjacent `.tar.gz.sig` to the NAS, then run:

```bash
sudo gravitynas-update /path/to/gravitynas-1.0.1.tar.gz
```

For HTTPS hosting, set `GRAVITYNAS_UPDATE_URL` in
`/etc/gravitynas/gravitynas.env` to the archive URL; its detached signature
must be available at the same URL with `.sig` appended. The updater verifies
the signature before extraction, installs dependencies into the new release,
switches the active link, and checks `/health`. If startup or health checking
fails, it restores the previous release and the pre-update SQLite database.
The private signing key must never be copied to the NAS.

## Runtime contract

- The service starts after the network is online and runs as `gravitynas`.
- Persistent application state is outside the release tree in `/var/lib/gravitynas`.
- The reverse proxy owns the HTTP boundary; remote tunneling remains disabled by default.
- Releases are immutable after installation; update code and mutable NAS data are stored separately.
- The image builder creates an appliance image, not a generic ISO for x86 computers.
