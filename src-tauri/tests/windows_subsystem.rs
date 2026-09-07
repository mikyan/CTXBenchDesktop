#![cfg(windows)]

#[test]
fn desktop_binary_uses_the_expected_windows_subsystem() {
    // Check the executable Cargo built, not just an attribute in the source.
    let bytes =
        std::fs::read(env!("CARGO_BIN_EXE_ctxbench-desktop")).expect("read the desktop executable");
    assert_eq!(&bytes[..2], b"MZ", "expected a Windows executable");
    let pe_offset = u32::from_le_bytes(bytes[0x3c..0x40].try_into().unwrap()) as usize;
    assert_eq!(&bytes[pe_offset..pe_offset + 4], b"PE\0\0");
    // The Subsystem field is at offset 68 in both PE32 and PE32+ optional headers.
    let subsystem_offset = pe_offset + 4 + 20 + 68;
    let subsystem = u16::from_le_bytes(
        bytes[subsystem_offset..subsystem_offset + 2]
            .try_into()
            .unwrap(),
    );
    let expected = if cfg!(debug_assertions) { 3 } else { 2 };
    assert_eq!(
        subsystem, expected,
        "release builds must use Windows GUI (2), debug builds Windows console (3)"
    );
}
