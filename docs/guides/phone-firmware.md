---
title: Phone firmware
summary: Upload the vendor's firmware for your phones and let Veyra update them, per profile or per phone.
audience: admin
section: Phones and devices
order: 80
reviewed: 0.27.45
pages:
  - /firmware/
covers:
  - frontend/src/app/(app)/firmware/*
  - backend/veyra/api/v1/firmware.py
---

Phones run software from their maker, called **firmware**. Veyra can keep your phones on the version you choose: you upload the vendor's firmware file once and assign it to a device profile. Each phone compares the version at its next check, updates itself and restarts.

If you assign nothing, Veyra leaves the phones' firmware alone.

## Upload a firmware image

1. Download the firmware file from the vendor's support site. For Poly VVX phones, that is the `sip.ld` file of the UC Software release. For Grandstream, keep the vendor's file name (for example `grp26xxafw.bin` or `gxp2170fw.bin`), because the phone asks for its file by name.
2. Open [Provisioning → Firmware](app:/firmware/) and choose **Upload firmware**.
3. Fill in:
   - **File:** the firmware file, up to 512 MB. Its name may contain only letters, digits, `.`, `_` and `-`. Do not rename it.
   - **Manufacturer** (required): pick it from the list, which shows the manufacturers Veyra has templates for. Profiles only offer images whose manufacturer matches their template's.
   - **Version** (required): the version number, for example `6.4.5.1234`. Type it exactly as the phone reports it, so Veyra can tell whether the phone is up to date.
   - **Models:** the models it is for, separated by commas, for example `VVX 411, VVX 450`. Leave it empty when the file fits every model of the manufacturer.
   - **Notes:** for your own records.
4. Choose **Upload**.

The list shows each image with its file name, models, size, the start of its SHA-256 checksum (to compare with the vendor's), who uploaded it, and how many profiles and phones it is assigned to.

**Edit** on a row changes the image's **Models** and **Notes**. To change the file, manufacturer or version, upload it again and delete the old image.

## Roll it out

1. Test on one phone first: open the phone under [Provisioning → Devices](app:/devices/) and choose the image under **Firmware override** on the **Settings** tab. Save, then choose **Reprovision**.
2. When it works, open the device profile under [Provisioning → Device Profiles](app:/device-profiles/), choose the image under **Firmware** and save. Every phone of the profile updates at its next daily check. To update one now, use **Reprovision** on its page.
3. Remove the test phone's override again (set **Firmware override** back to **From the profile**).

> **Warning:** A phone restarts to install firmware, which takes several minutes. It cannot make calls in the meantime. Roll out to a profile at a quiet time, or leave it to the phones' daily check, which runs at night by default.

Poly phones also go **down** to an older version if you assign one, so you can undo an update the same way.

## Check progress

On each phone's page, the **Status** tab shows under **Firmware**:

- **Assigned:** the version Veyra wants, and whether it comes from the profile or the phone.
- **Running:** the version the phone reported at its last check.
- **State:** **Up to date**, **Update pending**, or **Unknown** until the phone has checked in.

## Delete an image

The bin on a row works only when no profile or phone uses the image. Phones that already run the version are not affected.

## If something doesn't work

- **The image is not offered in a profile or on a phone.** Its **Manufacturer** does not match the template's manufacturer. Upload it again with the right manufacturer, then delete the old one.
- **"… is already uploaded."** The same manufacturer, version and file name exist already.
- **"Update pending" stays.** The phone has not checked in since, or the version you typed differs from what the phone reports. Compare **Running** with **Assigned**; if the phone runs the right firmware but the text differs, upload the image again with the version as the phone shows it.
- **The phone does not update.** Check that the file is the right one for the model. Some phones refuse firmware for another model, or a jump over several major versions; the vendor's release notes say which steps are needed.
