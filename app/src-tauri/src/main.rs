// Prevents an extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    if let Err(err) = openlocate_lib::run() {
        eprintln!("OpenLocate could not start: {err}");
        std::process::exit(1);
    }
}
