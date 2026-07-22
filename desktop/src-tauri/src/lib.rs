use tauri::{AppHandle, Emitter, Manager};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{TrayIconBuilder, TrayIconEvent};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use std::{
  process::Command,
  sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
  },
  time::{SystemTime, UNIX_EPOCH},
};

struct ChildState(Mutex<Option<tauri_plugin_shell::process::CommandChild>>);
struct TrayNoticeState(AtomicBool);
struct BackendStartupState(Mutex<Vec<BackendStartupStatus>>);
// The radar is a background service: quitting the window keeps the backend alive
// so reopening is instant. Only the tray "退出应用" sets this, causing a real exit.
struct ReallyExitState(AtomicBool);

#[derive(Clone, serde::Serialize)]
struct BackendStartupStatus {
  phase: String,
  message: String,
  detail: Option<String>,
  level: String,
  timestamp_ms: u64,
}

#[derive(serde::Serialize)]
struct BackendRuntimeSnapshot {
  processes: String,
  port_8765: String,
}

#[tauri::command]
fn get_backend_startup_statuses(
  state: tauri::State<'_, BackendStartupState>,
) -> Vec<BackendStartupStatus> {
  state.0.lock().map(|events| events.clone()).unwrap_or_default()
}

#[tauri::command]
fn get_backend_runtime_snapshot() -> BackendRuntimeSnapshot {
  BackendRuntimeSnapshot {
    processes: backend_process_snapshot(),
    port_8765: backend_port_snapshot(),
  }
}

#[cfg(windows)]
fn backend_process_snapshot() -> String {
  match Command::new("tasklist")
    .args(["/FI", "IMAGENAME eq backend-sidecar.exe", "/FO", "CSV"])
    .output()
  {
    Ok(output) => {
      let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
      let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
      if !stdout.is_empty() {
        stdout
      } else if !stderr.is_empty() {
        stderr
      } else {
        "tasklist returned no backend-sidecar.exe rows".to_string()
      }
    }
    Err(error) => format!("Failed to run tasklist: {}", error),
  }
}

#[cfg(not(windows))]
fn backend_process_snapshot() -> String {
  "Process snapshot is only implemented on Windows.".to_string()
}

#[cfg(windows)]
fn backend_port_snapshot() -> String {
  match Command::new("netstat").args(["-ano", "-p", "tcp"]).output() {
    Ok(output) => {
      let stdout = String::from_utf8_lossy(&output.stdout);
      let matches = stdout
        .lines()
        .filter(|line| line.contains(":8765"))
        .map(str::trim)
        .collect::<Vec<_>>();
      if matches.is_empty() {
        "No TCP listener or connection found for port 8765.".to_string()
      } else {
        matches.join("\n")
      }
    }
    Err(error) => format!("Failed to run netstat: {}", error),
  }
}

#[cfg(not(windows))]
fn backend_port_snapshot() -> String {
  "Port snapshot is only implemented on Windows.".to_string()
}

fn emit_backend_status(
  app: &AppHandle,
  phase: &str,
  message: impl Into<String>,
  detail: Option<String>,
  level: &str,
) {
  let timestamp_ms = SystemTime::now()
    .duration_since(UNIX_EPOCH)
    .map(|duration| duration.as_millis() as u64)
    .unwrap_or_default();
  let status = BackendStartupStatus {
    phase: phase.to_string(),
    message: message.into(),
    detail,
    level: level.to_string(),
    timestamp_ms,
  };

  let state = app.state::<BackendStartupState>();
  if let Ok(mut events) = state.0.lock() {
    events.push(status.clone());
    if events.len() > 80 {
      let overflow = events.len() - 80;
      events.drain(0..overflow);
    }
  }

  let _ = app.emit("backend-startup-status", status);
}

fn shutdown_backend_sidecar(app: &AppHandle) {
  let state = app.state::<ChildState>();
  if let Ok(mut lock) = state.0.lock() {
    if let Some(child) = lock.take() {
      let pid = child.pid();
      println!("[Tauri] Stopping backend sidecar pid {}.", pid);
      let _ = child.kill();
      kill_process_tree(pid);
    }
  }

  kill_backend_sidecar_by_name();
}

#[cfg(windows)]
fn kill_process_tree(pid: u32) {
  let pid_arg = pid.to_string();
  let _ = Command::new("taskkill")
    .args(["/PID", pid_arg.as_str(), "/T", "/F"])
    .status();
}

#[cfg(not(windows))]
fn kill_process_tree(_pid: u32) {}

#[cfg(windows)]
fn kill_backend_sidecar_by_name() {
  let _ = Command::new("taskkill")
    .args(["/IM", "backend-sidecar.exe", "/T", "/F"])
    .status();
}

#[cfg(not(windows))]
fn kill_backend_sidecar_by_name() {}

fn notify_hidden_to_tray(app: &AppHandle) {
  let state = app.state::<TrayNoticeState>();
  if state.0.swap(true, Ordering::Relaxed) {
    return;
  }

  let _ = app.notification()
    .builder()
    .title("MajorRSS is still running")
    .body("MajorRSS has been minimized to the system tray. Use the tray menu to exit the app completely.")
    .show();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .manage(ChildState(Mutex::new(None)))
    .manage(TrayNoticeState(AtomicBool::new(false)))
    .manage(BackendStartupState(Mutex::new(Vec::new())))
    .manage(ReallyExitState(AtomicBool::new(false)))
    .invoke_handler(tauri::generate_handler![
      get_backend_startup_statuses,
      get_backend_runtime_snapshot,
    ])
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
        .tooltip("MajorRSS is running in the background")
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
              app.state::<ReallyExitState>().0.store(true, Ordering::SeqCst);
              shutdown_backend_sidecar(app);
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
        let app_handle = app.handle().clone();
        let w = window.clone();
        window.on_window_event(move |event| {
          if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = w.hide();
            notify_hidden_to_tray(&app_handle);
          }
        });
      }

      // Launch the backend-sidecar in the background
      emit_backend_status(
        app.handle(),
        "sidecar_command",
        "Preparing packaged backend sidecar.",
        Some("Resolving backend-sidecar from the installed application resources.".to_string()),
        "info",
      );
      // Resolve the packaged backend from the bundled onedir resource.
      let backend_path = app.path().resource_dir().map(|d| {
        let name = if cfg!(windows) { "backend-sidecar.exe" } else { "backend-sidecar" };
        d.join("backend-bundle").join(name)
      });
      match backend_path {
        Ok(path) => {
          emit_backend_status(
            app.handle(),
            "sidecar_command_ready",
            "Backend sidecar command resolved.",
            Some("The packaged backend-sidecar executable was found.".to_string()),
            "success",
          );
          match app.shell().command(path.to_string_lossy().to_string()).spawn() {
            Ok((mut rx, child)) => {
              let pid = child.pid();
              println!("[Tauri] Backend sidecar spawned successfully.");
              emit_backend_status(
                app.handle(),
                "sidecar_spawned",
                "Backend sidecar process started.",
                Some(format!("backend-sidecar pid {}", pid)),
                "success",
              );
              
              let state = app.state::<ChildState>();
              if let Ok(mut lock) = state.0.lock() {
                *lock = Some(child);
              }
              
              // Spawn an async task to pipe sidecar stdout/stderr to console
              let app_handle = app.handle().clone();
              tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                  match event {
                    CommandEvent::Stdout(line) => {
                      let text = String::from_utf8_lossy(&line);
                      let trimmed = text.trim().to_string();
                      println!("[Sidecar stdout] {}", trimmed);
                      if !trimmed.is_empty() {
                        emit_backend_status(
                          &app_handle,
                          "sidecar_stdout",
                          "Backend stdout.",
                          Some(trimmed),
                          "info",
                        );
                      }
                    }
                    CommandEvent::Stderr(line) => {
                      let text = String::from_utf8_lossy(&line);
                      let trimmed = text.trim().to_string();
                      eprintln!("[Sidecar stderr] {}", trimmed);
                      if !trimmed.is_empty() {
                        emit_backend_status(
                          &app_handle,
                          "sidecar_stderr",
                          "Backend stderr.",
                          Some(trimmed),
                          "warning",
                        );
                      }
                    }
                    CommandEvent::Error(error) => {
                      emit_backend_status(
                        &app_handle,
                        "sidecar_event_error",
                        "Backend sidecar event error.",
                        Some(error),
                        "error",
                      );
                    }
                    CommandEvent::Terminated(payload) => {
                      let level = if payload.code == Some(0) { "info" } else { "error" };
                      emit_backend_status(
                        &app_handle,
                        "sidecar_launcher_terminated",
                        "Backend sidecar launcher process terminated.",
                        Some(format!(
                          "exit_code={:?}, signal={:?}. PyInstaller onefile builds may hand off from this launcher to a child process.",
                          payload.code,
                          payload.signal
                        )),
                        level,
                      );
                    }
                    _ => {}
                  }
                }
              });
            }
            Err(e) => {
              eprintln!("[Tauri ERROR] Failed to spawn backend sidecar: {:?}", e);
              emit_backend_status(
                app.handle(),
                "sidecar_spawn_failed",
                "Failed to start backend sidecar process.",
                Some(format!("{:?}", e)),
                "error",
              );
            }
          }
        }
        Err(e) => {
          eprintln!("[Tauri ERROR] Failed to create sidecar command: {:?}", e);
          emit_backend_status(
            app.handle(),
            "sidecar_command_failed",
            "Failed to resolve backend sidecar command.",
            Some(format!("{:?}", e)),
            "error",
          );
        }
      }

      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while running tauri application");

  app.run(|app_handle, event| match event {
    tauri::RunEvent::ExitRequested { api, .. } => {
      // Stay resident unless the user explicitly chose 退出应用: hide to tray and
      // keep the backend warm so the next open is instant (radar keeps running).
      let really = app_handle.state::<ReallyExitState>().0.load(Ordering::SeqCst);
      if really {
        return;
      }
      api.prevent_exit();
      if let Some(window) = app_handle.get_webview_window("main") {
        let _ = window.hide();
      }
      notify_hidden_to_tray(app_handle);
    }
    tauri::RunEvent::Exit => {
      shutdown_backend_sidecar(app_handle);
    }
    _ => {}
  });
}
