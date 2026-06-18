use tauri::Manager;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
      if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
      }
    }))
    .plugin(tauri_plugin_notification::init())
    .plugin(tauri_plugin_dialog::init())
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

      // Create system tray menu
      let show_item = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
      let hide_item = MenuItem::with_id(app, "hide", "隐藏到后台", true, None::<&str>)?;
      let exit_item = MenuItem::with_id(app, "exit", "退出应用", true, None::<&str>)?;
      
      let tray_menu = Menu::with_items(
        app,
        &[
          &show_item,
          &hide_item,
          &tauri::menu::PredefinedMenuItem::separator(app)?,
          &exit_item,
        ],
      )?;

      // Build system tray icon
      let tray_icon = app.default_window_icon().cloned();
      let mut tray_builder = TrayIconBuilder::new()
        .menu(&tray_menu)
        .show_menu_on_left_click(false);
      if let Some(icon) = tray_icon {
        tray_builder = tray_builder.icon(icon);
      }

      let _tray = tray_builder
        .on_menu_event(|app, event| {
          match event.id.as_ref() {
            "show" => {
              if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
              }
            }
            "hide" => {
              if let Some(window) = app.get_webview_window("main") {
                let _ = window.hide();
              }
            }
            "exit" => {
              app.exit(0);
            }
            _ => {}
          }
        })
        .on_tray_icon_event(|tray, event| {
          if let TrayIconEvent::Click { button, button_state, .. } = event {
            if button == tauri::tray::MouseButton::Left && button_state == tauri::tray::MouseButtonState::Up {
              let app = tray.app_handle();
              if let Some(window) = app.get_webview_window("main") {
                if window.is_visible().unwrap_or(false) {
                  let _ = window.hide();
                } else {
                  let _ = window.show();
                  let _ = window.set_focus();
                }
              }
            }
          }
        })
        .build(app)?;

      // Set window event listener to intercept close request and hide window
      if let Some(window) = app.get_webview_window("main") {
        let w = window.clone();
        window.on_window_event(move |event| {
          if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = w.hide();
          }
        });
      }

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
