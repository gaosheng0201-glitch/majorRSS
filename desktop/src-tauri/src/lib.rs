use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      
      // Initialize the shell plugin
      app.handle().plugin(tauri_plugin_shell::init())?;

      // Launch the backend-sidecar in the background
      match app.shell().sidecar("backend-sidecar") {
        Ok(sidecar) => {
          match sidecar.spawn() {
            Ok((mut rx, _child)) => {
              println!("[Tauri] Backend sidecar spawned successfully.");
              
              // Spawn an async task to pipe sidecar stdout/stderr to console
              tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                  match event {
                    CommandEvent::Stdout(line) => {
                      let text = String::from_utf8_lossy(&line);
                      println!("[Sidecar stdout] {}", text.trim());
                    }
                    CommandEvent::Stderr(line) => {
                      let text = String::from_utf8_lossy(&line);
                      eprintln!("[Sidecar stderr] {}", text.trim());
                    }
                    _ => {}
                  }
                }
              });
            }
            Err(e) => {
              eprintln!("[Tauri ERROR] Failed to spawn backend sidecar: {:?}", e);
            }
          }
        }
        Err(e) => {
          eprintln!("[Tauri ERROR] Failed to create sidecar command: {:?}", e);
        }
      }

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
