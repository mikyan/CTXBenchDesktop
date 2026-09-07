// Release builds are desktop applications; retain the console for development.
#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

fn main() {
    ctxbench_desktop_lib::run();
}
