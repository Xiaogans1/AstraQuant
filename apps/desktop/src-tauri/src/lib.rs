mod handshake;
mod runtime;

use runtime::{RuntimeConnection, RuntimeManager};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_opener::OpenerExt;

#[tauri::command]
fn runtime_connection(manager: State<'_, RuntimeManager>) -> Result<RuntimeConnection, String> {
    manager.connection().map_err(|error| error.to_string())
}

#[tauri::command]
fn open_log_directory(app: AppHandle, manager: State<'_, RuntimeManager>) -> Result<(), String> {
    app.opener()
        .open_path(manager.log_dir().to_string_lossy(), None::<&str>)
        .map_err(|error| error.to_string())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let manager = RuntimeManager::new();
            manager.start()?;
            app.manage(manager);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            runtime_connection,
            open_log_directory
        ])
        .build(tauri::generate_context!())
        .expect("error while building AstraQuant desktop");

    app.run(|app_handle, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            app_handle.state::<RuntimeManager>().shutdown();
        }
    });
}
