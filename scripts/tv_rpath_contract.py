"""Read-only frozen TouchColor TV Mach-O comparison. No signing, export, upload or credentials.

The two main-image validators are exact function-source copies from the reviewed
control before/after its four-line Touch-only path fix. This module contains no
private authorization, account, or credential configuration.
"""
import hashlib, json, os, plistlib, stat, struct
from pathlib import Path
from types import SimpleNamespace

class Blocked(ValueError): pass
def need(ok, reason):
    if not ok: raise Blocked(reason)
def digest(raw): return hashlib.sha256(raw).hexdigest()

ROUTES = {'cell-tv': {'bundle_id': 'Mango.Celluloid', 'executable': 'CelluloidTV', 'version': '1.1', 'build': '2', 'sdk': 'appletvos', 'supported_platform': 'AppleTVOS', 'device_family': 3, 'minimum_os': '17.0', 'sdk_version': '27.0', 'macho_platform': 3, 'resource_bundles': ['CelluloidCore_CelluloidDomain.bundle', 'CelluloidRendering_CelluloidRendering.bundle'], 'product': 'CelluloidTV', 'source_sha': '23948827aee96019a95eca7a24ed646d2d1f97cf', 'source_tree': 'f4df598b2a5a449c910972025036c0f37871bcb0'}, 'cell-vision': {'bundle_id': 'Mango.Celluloid', 'executable': 'CelluloidVision', 'version': '1.1', 'build': '2', 'sdk': 'xros', 'supported_platform': 'XROS', 'device_family': 7, 'minimum_os': '1.0', 'sdk_version': '27.0', 'macho_platform': 11, 'resource_bundles': ['CelluloidCore_CelluloidDomain.bundle', 'CelluloidRendering_CelluloidRendering.bundle'], 'product': 'CelluloidVision', 'source_sha': '83f83222cc7589b3b0829f0cb9fbc8342562993b', 'source_tree': 'f2b9115f3702c8e540cbbc2a47a466c2049367ba'}, 'qr-tv': {'bundle_id': '100mango.QRCatcher', 'executable': 'QRCatcherTV', 'version': '1.1', 'build': '2', 'sdk': 'appletvos', 'supported_platform': 'AppleTVOS', 'device_family': 3, 'minimum_os': '17.0', 'sdk_version': '27.0', 'macho_platform': 3, 'resource_bundles': [], 'product': 'QRCatcherTV', 'source_sha': '547dce14cda34946eb5bdaf28c0dc45dfabb33d8', 'source_tree': '2433d3345acd23156da4d6bc37cb6a84b9cb4be0'}, 'qr-vision': {'bundle_id': '100mango.QRCatcher', 'executable': 'QRCatcherVision', 'version': '1.1', 'build': '2', 'sdk': 'xros', 'supported_platform': 'XROS', 'device_family': 7, 'minimum_os': '1.0', 'sdk_version': '27.0', 'macho_platform': 11, 'resource_bundles': [], 'product': 'QRCatcherVision', 'source_sha': '6675f0051fbb597ed7212819cd34fb0b1e42c7b5', 'source_tree': 'f7cefb13a5ddf20b9564b67df094b52f2a37dce8'}, 'touch-tv': {'bundle_id': 'com.mango.touchColor', 'executable': 'TouchColor', 'version': '2.0.1', 'build': '20002', 'sdk': 'appletvos', 'supported_platform': 'AppleTVOS', 'device_family': 3, 'minimum_os': '17.0', 'sdk_version': '27.0', 'macho_platform': 3, 'resource_bundles': [], 'product': 'TouchColor', 'source_sha': '7c671f04e4d69884741a411851ae26083361c7f7', 'source_tree': 'f477c19b8181c4e3eb2142beaef4dea742cca0cd'}, 'touch-vision': {'bundle_id': 'com.mango.touchColor', 'executable': 'TouchColor', 'version': '2.0', 'build': '20001', 'sdk': 'xros', 'supported_platform': 'XROS', 'device_family': 7, 'minimum_os': '1.0', 'sdk_version': '27.0', 'macho_platform': 11, 'resource_bundles': [], 'product': 'TouchColor', 'source_sha': '0ebc518143c282e3a58a4e9e7972e93fde19b070', 'source_tree': 'abd68cfa8351cefde4d537d6ce988f512541eb04'}}
def spec(route):
    need(route in ROUTES, 'route_unknown')
    return ROUTES[route]
policy = SimpleNamespace(need=need, digest=digest, spec=spec, Blocked=Blocked, ROUTES=ROUTES)
MAX_BYTES = 100 * 1024 * 1024
SIGNED_ADDITIONS = {"embedded.mobileprovision", "_CodeSignature/CodeResources"}

"""Pure mature Mach-O parser, copied unchanged from reviewed iOS package proof."""
import struct
_PARSER_MACH_MAGICS = (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf")

def require(ok, message):
    if not ok:
        raise ValueError(message)

def version(number):
    return [number >> 16, (number >> 8) & 255, number & 255]

def mach_info(raw):
    """Read bounded 64-bit thin/fat headers and load commands, never execute."""
    require(len(raw) >= 32, 'Truncated Mach-O')
    magic = raw[:4]
    if magic in _PARSER_MACH_MAGICS[2:]:
        count = struct.unpack_from('>I', raw, 4)[0]
        width = 32 if magic == _PARSER_MACH_MAGICS[3] else 20
        require(0 < count <= 8 and 8 + width * count <= len(raw), 'Invalid fat architecture table')
        result, intervals, cpus = [], [], set()
        for i in range(count):
            pos = 8 + i * width
            cpu, subtype = struct.unpack_from('>II', raw, pos)
            if width == 32:
                offset, size, align, reserved = struct.unpack_from('>QQII', raw, pos + 8)
                require(reserved == 0, 'Invalid fat reserved value')
            else:
                offset, size, align = struct.unpack_from('>III', raw, pos + 8)
            require(cpu not in cpus and align <= 30 and offset % (1 << align) == 0,
                    'Duplicate or misaligned fat slice')
            require(offset >= 8 + width * count and size >= 32 and offset + size <= len(raw), 'Invalid fat slice bounds')
            require(all(offset + size <= a or offset >= b for a, b in intervals), 'Overlapping fat slices')
            require(raw[offset:offset + 4] in _PARSER_MACH_MAGICS[:2], 'Nested or unsupported Mach-O slice')
            slices = mach_info(raw[offset:offset + size])
            require(len(slices) == 1 and slices[0]['cpu'] == cpu and slices[0]['subtype'] == subtype, 'Fat slice identity mismatch')
            cpus.add(cpu); intervals.append((offset, offset + size)); result.extend(slices)
        return result
    require(magic in _PARSER_MACH_MAGICS[:2], 'Expected a 64-bit Mach-O product')
    endian = '<' if magic == _PARSER_MACH_MAGICS[0] else '>'
    _, cpu, subtype, kind, count, size, _, reserved = struct.unpack_from(endian + '8I', raw)
    require(reserved == 0 and kind in (2, 6, 8), 'Unsupported Mach-O type')
    require(0 < count <= 4096 and 32 + size <= len(raw), 'Invalid Mach-O command bounds')
    position, builds, links = 32, [], []
    for _ in range(count):
        require(position + 8 <= 32 + size, 'Truncated load command')
        command, length = struct.unpack_from(endian + 'II', raw, position)
        require(length >= 8 and length % 8 == 0 and position + length <= 32 + size, 'Invalid load command size')
        if command == 0x32:  # LC_BUILD_VERSION
            require(length >= 24, 'Short build version')
            platform, minimum, sdk, tools = struct.unpack_from(endian + '4I', raw, position + 8)
            require(length == 24 + tools * 8, 'Malformed build tool table')
            builds.append({'platform': platform, 'minimum': version(minimum), 'sdk': version(sdk)})
        if command in (0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023):
            require(length >= 24, 'Short dylib command')
            offset = struct.unpack_from(endian + 'I', raw, position + 8)[0]
            require(24 <= offset < length, 'Invalid dylib name offset')
            name = raw[position + offset:position + length]
            require(b'\0' in name, 'Unterminated dylib path')
            links.append(name.split(b'\0', 1)[0].decode('utf-8'))
        position += length
    require(position == 32 + size and len(builds) == 1, 'Missing, duplicate or inconsistent build version')
    return [{'cpu': cpu, 'subtype': subtype, 'kind': kind, **builds[0], 'libraries': links}]

macho = SimpleNamespace(mach_info=mach_info, MACH_MAGICS=_PARSER_MACH_MAGICS)
MACH_MAGICS = set(macho.MACH_MAGICS) | {b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca"}

def read_regular(path, maximum=MAX_BYTES):
    """Single owned/no-link file, immutable bounded read; never follow a link."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1 and
             not before.st_mode & 0o7000 and 0 < before.st_size <= maximum, "file_shape_invalid")
        data = bytearray()
        while block := os.read(fd, min(65536, maximum + 1 - len(data))):
            data.extend(block)
            need(len(data) <= before.st_size, "file_grew")
        after = os.fstat(fd)
        named = path.lstat()
        def identity(v): return (v.st_dev, v.st_ino, v.st_size, v.st_mode, v.st_nlink, v.st_mtime_ns, v.st_ctime_ns)
        need(identity(before) == identity(after) == identity(named) and len(data) == before.st_size, "file_changed")
        return bytes(data)
    finally: os.close(fd)


def load_plist(raw):
    need(len(raw) <= 1024*1024, "plist_too_large")
    try: value = plistlib.loads(raw)
    except Exception: raise policy.Blocked("plist_invalid") from None
    need(type(value) is dict, "plist_dictionary_required")
    return value


def validate_info(route, info):
    s = policy.spec(route)
    expected = {"CFBundleIdentifier": s["bundle_id"], "CFBundleExecutable": s["executable"],
        "CFBundleShortVersionString": s["version"], "CFBundleVersion": s["build"],
        "CFBundlePackageType": "APPL", "DTPlatformName": s["sdk"],
        "CFBundleSupportedPlatforms": [s["supported_platform"]], "UIDeviceFamily": [s["device_family"]],
        "MinimumOSVersion": s["minimum_os"], "DTSDKName": s["sdk"] + s["sdk_version"]}
    need(all(info.get(k) == v and type(info.get(k)) is type(v) for k, v in expected.items()), "platform_plist_mismatch")
    need(not info.get("NSExtension") and not info.get("WKWatchKitApp") and not info.get("LSRequiresIPhoneOS"),
         "foreign_platform_metadata")
    return info


def inspect_macho(route, raw, signed):
    """Thin arm64 only, exact platform, bounded signature and executable sections.

Section hashes and normalized load-command bytes bind executable code across
export signing; only the signature command/data and __LINKEDIT length may vary.
"""
    s = policy.spec(route)
    need(raw[:4] == b"\xcf\xfa\xed\xfe", "thin_little_endian_arm64_required")
    try: rows = macho.mach_info(raw)
    except (ValueError, UnicodeError, struct.error): raise policy.Blocked("macho_invalid") from None
    need(len(rows) == 1, "single_architecture_required")
    row = rows[0]
    minimum = [int(x) for x in s["minimum_os"].split(".")] + [0]
    sdk = [int(x) for x in s["sdk_version"].split(".")] + [0]
    need(row["cpu"] == 0x100000c and row["subtype"] == 0 and row["kind"] == 2 and
         row["platform"] == s["macho_platform"] and row["minimum"] == minimum and row["sdk"] == sdk,
         "macho_platform_mismatch")
    need(all(x.startswith(("/System/Library/Frameworks/", "/usr/lib/")) or
             x.startswith("@rpath/libswift") and x.endswith(".dylib") for x in row["libraries"]), "non_system_library")
    count, size = struct.unpack_from("<II", raw, 16)
    pos, signatures, normalized, sections, intervals, linkedit = 32, [], [], {}, [], []
    normalized_commands = []
    rpath_classes = []
    for _ in range(count):
        command, length = struct.unpack_from("<II", raw, pos)
        data = bytearray(raw[pos:pos+length])
        if command == 0x1d:
            need(length == 16, "code_signature_command_invalid")
            offset, n = struct.unpack_from("<II", data, 8)
            if signed:
                need(n > 0 and offset >= 32 + size and offset+n == len(raw), "code_signature_bounds_invalid")
            else:
                need(n == 0 and offset in (0, len(raw)), "unsigned_signature_placeholder_invalid")
            signatures.append((offset, n))
        else:
            if command == 0x19:
                need(length >= 72, "segment_command_invalid")
                name = bytes(data[8:24]).split(b"\0", 1)[0]
                nsects = struct.unpack_from("<I", data, 64)[0]
                need(length == 72 + nsects*80, "segment_sections_invalid")
                if name == b"__LINKEDIT":
                    need(nsects == 0, "linkedit_sections_forbidden")
                    fileoff, filesize = struct.unpack_from("<QQ", data, 40)
                    need(fileoff >= 32+size and fileoff+filesize <= len(raw), "linkedit_bounds_invalid")
                    linkedit.append((fileoff, filesize))
                    data[32:40] = b"\0"*8  # vmsize changes with signature allocation.
                    data[48:56] = b"\0"*8  # filesize changes with signature allocation.
                for index in range(nsects):
                    p = 72 + index*80
                    section_name = bytes(data[p:p+16]).split(b"\0", 1)[0]
                    segment_name = bytes(data[p+16:p+32]).split(b"\0", 1)[0]
                    n = struct.unpack_from("<Q", data, p+40)[0]
                    offset = struct.unpack_from("<I", data, p+48)[0]
                    flags = struct.unpack_from("<I", data, p+64)[0]
                    key = (segment_name+b"/"+section_name).hex()
                    need(key not in sections, "duplicate_macho_section")
                    if flags & 0xff in (1, 0xc, 0x12):
                        sections[key] = {"zero_fill_bytes": n}
                    else:
                        need(offset >= 32+size and offset+n <= len(raw) and
                             all(offset+n <= a or offset >= b for a,b in intervals), "macho_section_bounds")
                        intervals.append((offset, offset+n))
                        sections[key] = {"sha256": policy.digest(raw[offset:offset+n]), "bytes": n}
            if command == 0x8000001c:
                need(length >= 16, "rpath_command_invalid")
                offset = struct.unpack_from("<I", data, 8)[0]
                need(12 <= offset < length and b"\0" in data[offset:], "rpath_invalid")
                path = bytes(data[offset:]).split(b"\0", 1)[0]
                category = {b"@executable_path/Frameworks": "executable_frameworks",
                            b"@executable_path/../Frameworks": "executable_parent_frameworks",
                            b"/usr/lib/swift": "system_swift"}.get(path)
                # Exact pinned QRCatcherTV Release setting. For this main MH_EXECUTE
                # image, loader_path and executable_path resolve to the same folder.
                if route == "qr-tv" and path == b"@loader_path/Frameworks":
                    category = "qr_main_loader_frameworks"
                need(category is not None, "rpath_not_allowlisted")
                rpath_classes.append(category)
            normalized.append(policy.digest(data))
            normalized_commands.append(bytes(data))
        pos += length
    need(len(signatures) == 1 if signed else len(signatures) <= 1, "macho_signature_state_invalid")
    need(bool(sections), "macho_sections_required")
    if signed:
        need(all(b <= signatures[0][0] for _, b in intervals), "signature_overlaps_code")
    need(len(linkedit) == 1, "single_linkedit_required")
    start, length = linkedit[0]
    need(start+length == len(raw), "trailing_macho_bytes_forbidden")
    canonical_header = bytearray(raw[:32])
    canonical_commands = b"".join(normalized_commands)
    struct.pack_into("<II", canonical_header, 16, count-len(signatures), len(canonical_commands))
    canonical_prefix = canonical_header+canonical_commands+b"\0"*(16*len(signatures))+raw[32+size:start]
    need(len(canonical_prefix) == start, "macho_header_normalization_invalid")
    prefix_hash = policy.digest(canonical_prefix)
    stop = start+length
    if signed:
        need(signatures[0][0] >= start and signatures[0][0]+signatures[0][1] == stop,
             "signature_outside_linkedit")
        stop = signatures[0][0]
    # Signing can append alignment padding before its signature; no other
    # __LINKEDIT mutation is admitted by this continuity fingerprint.
    linkedit_hash = policy.digest(raw[start:stop].rstrip(b"\0"))
    return {"metadata": row, "header_flags": struct.unpack_from("<I", raw, 24)[0], "load_commands": normalized, "sections": sections,
            "linkedit_sha256": linkedit_hash, "image_prefix_sha256": prefix_hash, "rpath_classes": rpath_classes}


inspect_macho_original = inspect_macho

def inspect_macho(route, raw, signed):
    """Thin arm64 only, exact platform, bounded signature and executable sections.

Section hashes and normalized load-command bytes bind executable code across
export signing; only the signature command/data and __LINKEDIT length may vary.
"""
    s = policy.spec(route)
    need(raw[:4] == b"\xcf\xfa\xed\xfe", "thin_little_endian_arm64_required")
    try: rows = macho.mach_info(raw)
    except (ValueError, UnicodeError, struct.error): raise policy.Blocked("macho_invalid") from None
    need(len(rows) == 1, "single_architecture_required")
    row = rows[0]
    minimum = [int(x) for x in s["minimum_os"].split(".")] + [0]
    sdk = [int(x) for x in s["sdk_version"].split(".")] + [0]
    need(row["cpu"] == 0x100000c and row["subtype"] == 0 and row["kind"] == 2 and
         row["platform"] == s["macho_platform"] and row["minimum"] == minimum and row["sdk"] == sdk,
         "macho_platform_mismatch")
    need(all(x.startswith(("/System/Library/Frameworks/", "/usr/lib/")) or
             x.startswith("@rpath/libswift") and x.endswith(".dylib") for x in row["libraries"]), "non_system_library")
    count, size = struct.unpack_from("<II", raw, 16)
    pos, signatures, normalized, sections, intervals, linkedit = 32, [], [], {}, [], []
    normalized_commands = []
    rpath_classes = []
    for _ in range(count):
        command, length = struct.unpack_from("<II", raw, pos)
        data = bytearray(raw[pos:pos+length])
        if command == 0x1d:
            need(length == 16, "code_signature_command_invalid")
            offset, n = struct.unpack_from("<II", data, 8)
            if signed:
                need(n > 0 and offset >= 32 + size and offset+n == len(raw), "code_signature_bounds_invalid")
            else:
                need(n == 0 and offset in (0, len(raw)), "unsigned_signature_placeholder_invalid")
            signatures.append((offset, n))
        else:
            if command == 0x19:
                need(length >= 72, "segment_command_invalid")
                name = bytes(data[8:24]).split(b"\0", 1)[0]
                nsects = struct.unpack_from("<I", data, 64)[0]
                need(length == 72 + nsects*80, "segment_sections_invalid")
                if name == b"__LINKEDIT":
                    need(nsects == 0, "linkedit_sections_forbidden")
                    fileoff, filesize = struct.unpack_from("<QQ", data, 40)
                    need(fileoff >= 32+size and fileoff+filesize <= len(raw), "linkedit_bounds_invalid")
                    linkedit.append((fileoff, filesize))
                    data[32:40] = b"\0"*8  # vmsize changes with signature allocation.
                    data[48:56] = b"\0"*8  # filesize changes with signature allocation.
                for index in range(nsects):
                    p = 72 + index*80
                    section_name = bytes(data[p:p+16]).split(b"\0", 1)[0]
                    segment_name = bytes(data[p+16:p+32]).split(b"\0", 1)[0]
                    n = struct.unpack_from("<Q", data, p+40)[0]
                    offset = struct.unpack_from("<I", data, p+48)[0]
                    flags = struct.unpack_from("<I", data, p+64)[0]
                    key = (segment_name+b"/"+section_name).hex()
                    need(key not in sections, "duplicate_macho_section")
                    if flags & 0xff in (1, 0xc, 0x12):
                        sections[key] = {"zero_fill_bytes": n}
                    else:
                        need(offset >= 32+size and offset+n <= len(raw) and
                             all(offset+n <= a or offset >= b for a,b in intervals), "macho_section_bounds")
                        intervals.append((offset, offset+n))
                        sections[key] = {"sha256": policy.digest(raw[offset:offset+n]), "bytes": n}
            if command == 0x8000001c:
                need(length >= 16, "rpath_command_invalid")
                offset = struct.unpack_from("<I", data, 8)[0]
                need(12 <= offset < length and b"\0" in data[offset:], "rpath_invalid")
                path = bytes(data[offset:]).split(b"\0", 1)[0]
                category = {b"@executable_path/Frameworks": "executable_frameworks",
                            b"@executable_path/../Frameworks": "executable_parent_frameworks",
                            b"/usr/lib/swift": "system_swift"}.get(path)
                # Exact pinned QRCatcherTV Release setting. For this main MH_EXECUTE
                # image, loader_path and executable_path resolve to the same folder.
                if route == "qr-tv" and path == b"@loader_path/Frameworks":
                    category = "qr_main_loader_frameworks"
                # Exact pinned TouchColorTV Release setting; the main MH_EXECUTE
                # requirement above also makes this resolve inside its app bundle.
                if route == "touch-tv" and path == b"@loader_path/Frameworks":
                    category = "touch_main_loader_frameworks"
                need(category is not None, "rpath_not_allowlisted")
                rpath_classes.append(category)
            normalized.append(policy.digest(data))
            normalized_commands.append(bytes(data))
        pos += length
    need(len(signatures) == 1 if signed else len(signatures) <= 1, "macho_signature_state_invalid")
    need(bool(sections), "macho_sections_required")
    if signed:
        need(all(b <= signatures[0][0] for _, b in intervals), "signature_overlaps_code")
    need(len(linkedit) == 1, "single_linkedit_required")
    start, length = linkedit[0]
    need(start+length == len(raw), "trailing_macho_bytes_forbidden")
    canonical_header = bytearray(raw[:32])
    canonical_commands = b"".join(normalized_commands)
    struct.pack_into("<II", canonical_header, 16, count-len(signatures), len(canonical_commands))
    canonical_prefix = canonical_header+canonical_commands+b"\0"*(16*len(signatures))+raw[32+size:start]
    need(len(canonical_prefix) == start, "macho_header_normalization_invalid")
    prefix_hash = policy.digest(canonical_prefix)
    stop = start+length
    if signed:
        need(signatures[0][0] >= start and signatures[0][0]+signatures[0][1] == stop,
             "signature_outside_linkedit")
        stop = signatures[0][0]
    # Signing can append alignment padding before its signature; no other
    # __LINKEDIT mutation is admitted by this continuity fingerprint.
    linkedit_hash = policy.digest(raw[start:stop].rstrip(b"\0"))
    return {"metadata": row, "header_flags": struct.unpack_from("<I", raw, 24)[0], "load_commands": normalized, "sections": sections,
            "linkedit_sha256": linkedit_hash, "image_prefix_sha256": prefix_hash, "rpath_classes": rpath_classes}


def inspect_app(route, app, *, signed=False):
    s = policy.spec(route)
    need(app.is_dir() and not app.is_symlink() and app.name == s["product"]+".app", "main_app_path_mismatch")
    inventory, bundles, total, executable_contract = {}, set(), 0, None
    pending = [app]
    count = 0
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            count += 1
            need(count <= 5000, "payload_entry_limit")
            rel = path.relative_to(app).as_posix()
            st = path.lstat()
            need(not path.is_symlink() and not st.st_mode & 0o7000 and st.st_uid == os.geteuid(), "unsafe_payload_entry")
            lower = path.name.lower()
            need(not lower.endswith((".app", ".appex", ".framework", ".dylib", ".xctest", ".dsym", ".p8", ".p12")) and
                 path.name not in ("Watch", "PlugIns", "Frameworks") and "fixture" not in lower and "xctest" not in lower,
                 "unexpected_code_payload")
            if stat.S_ISDIR(st.st_mode):
                if lower.endswith(".bundle"):
                    need(path.parent == app, "nested_resource_bundle")
                    bundles.add(path.name)
                pending.append(path)
                continue
            need(stat.S_ISREG(st.st_mode), "special_payload_entry")
            if not signed:
                need(not lower.endswith(".mobileprovision") and "_CodeSignature" not in path.parts, "unsigned_signing_payload")
            elif lower.endswith(".mobileprovision") or "_CodeSignature" in path.parts:
                need(rel in SIGNED_ADDITIONS, "unexpected_signing_payload")
            raw = read_regular(path)
            total += len(raw)
            need(total <= 512*1024*1024, "payload_byte_limit")
            inventory[rel] = {"sha256": policy.digest(raw), "bytes": len(raw)}
            if rel == s["executable"]:
                executable_contract = inspect_macho(route, raw, signed)
            else:
                need(raw[:4] not in MACH_MAGICS and not st.st_mode & 0o111, "hidden_executable_payload")
                if lower == "info.plist" and rel != "Info.plist":
                    resource_info = load_plist(raw)
                    need(not resource_info.get("CFBundleExecutable") and not resource_info.get("NSExtension"), "executable_resource_bundle")
    need(bundles == set(s["resource_bundles"]), "resource_bundle_inventory_mismatch")
    need(executable_contract is not None and {"Info.plist", "PkgInfo", "Assets.car"} <= set(inventory), "required_payload_missing")
    if signed: need(SIGNED_ADDITIONS <= set(inventory), "signature_payload_missing")
    info = validate_info(route, load_plist(read_regular(app/"Info.plist", 1024*1024)))
    need(read_regular(app/"PkgInfo", 16) == b"APPL????", "package_type_mismatch")
    return {"route": route, "source_sha": s["source_sha"], "source_tree": s["source_tree"],
            "files": inventory, "info": info, "executable_contract": executable_contract,
            "signature_verified": False, "profile_trust_verified": False}


ORIGINAL_VALIDATOR_SHA256 = '9980e62c2041caaf96d7fcad79549975176e09cbc52e36c0204b5a2cf40597d4'
FIXED_VALIDATOR_SHA256 = 'd17ee118a7e41039e272d2c2735ca90314f537b5f72e9f17a90d195d3f6449a1'

def read_binary(path):
    """Read one bounded owned file without following links or racing replacement."""
    maximum = 64 * 1024 * 1024
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not (stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                before.st_nlink == 1 and not before.st_mode & 0o7000 and
                32 <= before.st_size <= maximum):
            raise ValueError('bounded owned single-link regular Mach-O required')
        value = bytearray()
        while block := os.read(fd, min(65536, maximum + 1 - len(value))):
            value.extend(block)
            if len(value) > before.st_size:
                raise ValueError('file grew during inspection')
        after, named = os.fstat(fd), path.lstat()
        def identity(st):
            return (st.st_dev, st.st_ino, st.st_size, st.st_mode, st.st_uid,
                    st.st_nlink, st.st_mtime_ns, st.st_ctime_ns)
        if identity(before) != identity(after) or identity(before) != identity(named) or len(value) != before.st_size:
            raise ValueError('file changed during inspection')
        return bytes(value)
    finally:
        os.close(fd)


def inspect(path):
    if 'APP_STORE_CONNECT_PRIVATE_KEY' in os.environ:
        raise ValueError('Apple credential environment forbidden')
    return inspect_rpath_bytes(read_binary(path))


def inspect_rpath_bytes(raw):
    if not isinstance(raw, bytes) or not 32 <= len(raw) <= 64 * 1024 * 1024:
        raise ValueError('bounded Mach-O bytes required')
    magic,cpu,subtype,kind,count,size,flags,reserved = struct.unpack_from('<8I',raw)
    if magic != 0xfeedfacf or cpu != 0x100000c or subtype != 0 or kind != 2 or reserved != 0:
        raise ValueError('expected thin arm64 main MH_EXECUTE')
    if not 0 < count <= 2048 or not count*8 <= size <= 4*1024*1024 or 32+size > len(raw):
        raise ValueError('invalid load-command bounds')
    rpaths=[]; signatures=[]; builds=[]; pos=32
    for index in range(count):
        if pos+8 > 32+size:
            raise ValueError('truncated command')
        command,length=struct.unpack_from('<II',raw,pos)
        if length < 8 or length % 8 or pos+length > 32+size:
            raise ValueError('invalid command length')
        if command == 0x32:
            if length < 24:
                raise ValueError('invalid build command')
            platform, minimum, sdk, tool_count = struct.unpack_from('<4I',raw,pos+8)
            if length != 24 + tool_count * 8:
                raise ValueError('invalid build tools')
            builds.append((platform, minimum, sdk))
        if command == 0x8000001c:
            if length < 16:
                raise ValueError('invalid rpath command')
            offset=struct.unpack_from('<I',raw,pos+8)[0]
            if not 12 <= offset < length:
                raise ValueError('invalid rpath offset')
            tail=raw[pos+offset:pos+length]
            if b'\0' not in tail:
                raise ValueError('unterminated rpath')
            value=tail.split(b'\0',1)[0]
            if not value or len(value)>256 or len(rpaths)>=32:
                raise ValueError('invalid rpath size')
            rpaths.append({'command_index':index,'path_utf8':value.decode('utf-8','strict'),
                           'path_hex':value.hex()})
        if command == 0x1d:
            if length != 16:
                raise ValueError('invalid signature command')
            offset,bytes_count=struct.unpack_from('<II',raw,pos+8)
            signatures.append({'offset':offset,'bytes':bytes_count})
        pos += length
    if pos != 32+size or len(signatures)>1 or any(x['bytes']!=0 or x['offset'] not in (0,len(raw)) for x in signatures):
        raise ValueError('not an unsigned bounded executable')
    if builds != [(3, 17 << 16, 27 << 16)]:
        raise ValueError('expected exact tvOS 17.0 minimum and 27.0 SDK')
    return {'status':'UNSIGNED_RPATH_DIAGNOSTIC_ONLY','executable_sha256':hashlib.sha256(raw).hexdigest(),
            'bytes':len(raw),'cpu':'arm64','filetype':'MH_EXECUTE','macho_platform':3,
            'minimum_os':'17.0','sdk_version':'27.0','rpaths':rpaths,
            'signature_commands':signatures,'signed_export':False,'upload_invoked':False,
            'release_policy_modified':False,'release_qualification':False}

inspect_rpaths = inspect
