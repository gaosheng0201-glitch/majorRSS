!macro MAJORRSS_STOP_PROCESS IMAGE_NAME
  DetailPrint "Stopping ${IMAGE_NAME} if it is running..."
  nsExec::ExecToLog '"$SYSDIR\taskkill.exe" /IM "${IMAGE_NAME}" /F /T'
!macroend

!macro MAJORRSS_CLOSE_RUNNING_APP ACTION_NAME
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
  ${OrIf} ${FileExists} "$INSTDIR\backend-sidecar.exe"
    ${If} $PassiveMode != 1
      MessageBox MB_ICONINFORMATION|MB_OKCANCEL "MajorRSS or its local backend may still be running. The installer will close app.exe and backend-sidecar.exe before ${ACTION_NAME}." IDOK +2
      Abort
    ${EndIf}

    !insertmacro MAJORRSS_STOP_PROCESS "${MAINBINARYNAME}.exe"
    !insertmacro MAJORRSS_STOP_PROCESS "backend-sidecar.exe"
    Sleep 1000
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro MAJORRSS_CLOSE_RUNNING_APP "installing files"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro MAJORRSS_CLOSE_RUNNING_APP "uninstalling files"
!macroend
