Attribute VB_Name = "MailPlusAutomation"
Option Explicit

'==============================================================
' MailPlus Automation - Outlook VBA Macros
'==============================================================
' Configuration
' No user-specific paths are stored here. The project folder is
' read from the MAILPLUS_HOME environment variable. Set it once:
'     setx MAILPLUS_HOME "C:\path\to\outlook-automation"
' (Close and reopen Outlook after setting it.)
' Secrets live in the project's .env file, not in this module.
'==============================================================
Private Const PY_SCRIPT_NAME As String = "mailplus_automation.py"
Private Const SPAM_REPORT_EMAIL_FALLBACK As String = "spam@yourdomain.com"

'==============================================================
' Helpers: resolve project paths from MAILPLUS_HOME
'==============================================================
Private Function ProjectDir() As String
    Dim p As String
    p = Environ("MAILPLUS_HOME")
    If Len(p) = 0 Then Exit Function
    ' Strip trailing backslash (VBA And does not short-circuit, so nest the checks)
    Do While Len(p) > 0
        If Right$(p, 1) <> "\" Then Exit Do
        p = Left$(p, Len(p) - 1)
    Loop
    ProjectDir = p
End Function

Private Function PythonExe() As String
    PythonExe = ProjectDir() & "\.venv\Scripts\python.exe"
End Function

Private Function ScriptPath() As String
    ScriptPath = ProjectDir() & "\" & PY_SCRIPT_NAME
End Function

'==============================================================
' Helper: read a KEY=VALUE line from the project's .env file
'==============================================================
Private Function DotEnvValue(key As String) As String
    Dim fso As Object, ts As Object, line As String, v As String
    Dim envPath As String
    DotEnvValue = ""

    envPath = ProjectDir() & "\.env"
    If Len(envPath) = 0 Then Exit Function

    Set fso = CreateObject("Scripting.FileSystemObject")
    If Not fso.FileExists(envPath) Then Exit Function

    Set ts = fso.OpenTextFile(envPath, 1)   ' 1 = ForReading
    Do Until ts.AtEndOfStream
        line = Trim$(ts.ReadLine)
        If Len(line) > 0 Then
            If Left$(line, 1) <> "#" And InStr(line, "=") > 0 Then
                If Left$(line, Len(key) + 1) = key & "=" Then
                    v = Trim$(Mid$(line, Len(key) + 2))
                    If Len(v) >= 2 Then
                        If (Left$(v, 1) = """" And Right$(v, 1) = """") _
                        Or (Left$(v, 1) = "'" And Right$(v, 1) = "'") Then
                            v = Mid$(v, 2, Len(v) - 2)
                        End If
                    End If
                    DotEnvValue = v
                    ts.Close
                    Exit Function
                End If
            End If
        End If
    Loop
    ts.Close
End Function

'==============================================================
' ACTION 1: Mark as Spam
' Forwards the selected email as attachment to spam reporting address
'==============================================================
Public Sub Spam()
    Dim olApp As Outlook.Application
    Dim olExp As Outlook.Explorer
    Dim sel As Selection
    Dim item As Object
    Dim mail As MailItem
    Dim forwarded As MailItem
    Dim processedCount As Integer
    
    Set olApp = Application
    Set olExp = olApp.ActiveExplorer
    
    If olExp Is Nothing Then
        MsgBox "No active explorer window found.", vbExclamation, "Error"
        GoTo Cleanup
    End If
    
    Set sel = olExp.Selection
    
    If sel.Count = 0 Then
        MsgBox "Please select at least one email first.", vbExclamation, "No Selection"
        GoTo Cleanup
    End If
    
    processedCount = 0
    Dim spamEmail As String
    spamEmail = DotEnvValue("SPAM_REPORT_EMAIL")
    If Len(spamEmail) = 0 Then spamEmail = SPAM_REPORT_EMAIL_FALLBACK
    
    For Each item In sel
        If TypeOf item Is MailItem Then
            Set mail = item
            
            ' Forward as attachment (CreateItem avoids ForwardAsAttachment compatibility issues)
            Set forwarded = Application.CreateItem(olMailItem)
            forwarded.To = spamEmail
            forwarded.Subject = "Spam Report: " & mail.Subject
            forwarded.Body = "Forwarded as spam attachment." & vbCrLf & vbCrLf & "--- Original Message ---"
            forwarded.Attachments.Add mail
            forwarded.Send
            
            processedCount = processedCount + 1
        End If
    Next item
    
    If processedCount > 0 Then
        MsgBox processedCount & " email(s) forwarded as spam to " & spamEmail & ".", vbInformation, "Spam Reported"
    Else
        MsgBox "No valid mail items were selected.", vbExclamation, "Error"
    End If
    
Cleanup:
    Set mail = Nothing
    Set forwarded = Nothing
    Set sel = Nothing
    Set olExp = Nothing
    Set olApp = Nothing
End Sub

'==============================================================
' ACTION 2: Block Sender
' Adds the sender of the selected email to Synology MailPlus block list
'==============================================================
Public Sub Block()
    Dim olApp As Outlook.Application
    Dim olExp As Outlook.Explorer
    Dim sel As Selection
    Dim item As Object
    Dim mail As MailItem
    Dim senderEmail As String
    Dim subject As String
    Dim result As Integer
    
    Set olApp = Application
    Set olExp = olApp.ActiveExplorer
    
    If olExp Is Nothing Then
        MsgBox "No active explorer window found.", vbExclamation, "Error"
        GoTo Cleanup
    End If
    
    Set sel = olExp.Selection
    
    If sel.Count = 0 Then
        MsgBox "Please select an email first.", vbExclamation, "No Selection"
        GoTo Cleanup
    End If
    
    ' Use the first selected mail item
    Set item = sel.Item(1)
    
    If Not TypeOf item Is MailItem Then
        MsgBox "Selected item is not a mail message.", vbExclamation, "Error"
        GoTo Cleanup
    End If
    
    Set mail = item
    senderEmail = GetSenderEmail(mail)
    subject = mail.Subject
    
    If senderEmail = "" Then
        MsgBox "Could not determine sender email address.", vbExclamation, "Error"
        GoTo Cleanup
    End If
    
    result = RunPowerShellScript("Block", senderEmail, subject)
    
    If result = 0 Then
        MsgBox "Block rule created for: " & senderEmail, vbInformation, "Success"
    Else
        MsgBox "Failed to create block rule. Check the log at:" & vbCrLf & _
                ProjectDir() & "\logs", vbExclamation, "Error"
    End If
    
Cleanup:
    Set mail = Nothing
    Set sel = Nothing
    Set olExp = Nothing
    Set olApp = Nothing
End Sub

'==============================================================
' ACTION 3: Release from Quarantine
' Opens Synology MailPlus MCP Quarantine and releases emails from sender
'==============================================================
Public Sub Release()
    Dim olApp As Outlook.Application
    Dim olExp As Outlook.Explorer
    Dim sel As Selection
    Dim item As Object
    Dim mail As MailItem
    Dim senderEmail As String
    Dim subject As String
    Dim result As Integer
    
    Set olApp = Application
    Set olExp = olApp.ActiveExplorer
    
    If olExp Is Nothing Then
        MsgBox "No active explorer window found.", vbExclamation, "Error"
        GoTo Cleanup
    End If
    
    Set sel = olExp.Selection
    
    If sel.Count = 0 Then
        MsgBox "Please select the quarantine notification email first.", vbExclamation, "No Selection"
        GoTo Cleanup
    End If
    
    ' Use the first selected mail item
    Set item = sel.Item(1)
    
    If Not TypeOf item Is MailItem Then
        MsgBox "Selected item is not a mail message.", vbExclamation, "Error"
        GoTo Cleanup
    End If
    
    Set mail = item
    senderEmail = GetSenderEmail(mail)
    subject = mail.Subject
    
    ' Call PowerShell script
    result = RunPowerShellScript("Release", senderEmail, subject)
    
    If result = 0 Then
        MsgBox "Email released from MCP Quarantine.", vbInformation, "Released"
    Else
        MsgBox "Failed to release from quarantine. Check the log at:" & vbCrLf & _
                ProjectDir() & "\logs", vbExclamation, "Error"
    End If
    
Cleanup:
    Set mail = Nothing
    Set sel = Nothing
    Set olExp = Nothing
    Set olApp = Nothing
End Sub

'==============================================================
' Helper: Extract sender email from a MailItem
' Handles Exchange users, SMTP addresses, and one-off addresses
'==============================================================
Private Function GetSenderEmail(mail As MailItem) As String
    On Error Resume Next
    
    Dim senderAddr As String
    senderAddr = ""
    
    ' Try sender properties in order of reliability
    If mail.SenderEmailType = "EX" Then
        ' Exchange recipient - try to get SMTP address
        Dim exchUser As ExchangeUser
        Set exchUser = mail.Sender.GetExchangeUser()
        If Not exchUser Is Nothing Then
            senderAddr = exchUser.PrimarySmtpAddress
        End If
        Set exchUser = Nothing
    End If
    
    ' Fall back to direct properties
    If senderAddr = "" Then
        senderAddr = mail.SenderEmailAddress
    End If
    
    ' Property-based extraction
    If senderAddr = "" Then
        Dim propVal As Variant
        propVal = mail.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x5D01001E")
        If Not IsError(propVal) Then
            senderAddr = CStr(propVal)
        End If
    End If
    
    ' Final fallback - parse from the PR_SENDER_SMTP_ADDRESS
    If senderAddr = "" Then
        propVal = mail.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x5D01001F")
        If Not IsError(propVal) Then
            senderAddr = CStr(propVal)
        End If
    End If
    
    ' Clean up: remove display name if present (e.g. "John <john@abc.com>")
    If InStr(senderAddr, "<") > 0 And InStr(senderAddr, ">") > 0 Then
        senderAddr = Mid(senderAddr, InStr(senderAddr, "<") + 1)
        senderAddr = Left(senderAddr, Len(senderAddr) - 1)
    End If
    
    GetSenderEmail = senderAddr
End Function

'==============================================================
' Helper: Run Python script and wait for completion
' Returns exit code (0 = success)
'==============================================================
Private Function RunPowerShellScript(action As String, senderEmail As String, subject As String) As Integer
    Dim wsh As Object
    Dim cmd As String
    Dim exitCode As Integer
    Dim argsFile As String
    Dim fso As Object
    Dim homeDir As String
    Dim pyExe As String
    Dim scriptFile As String
    Dim logsDir As String

    Set fso = CreateObject("Scripting.FileSystemObject")
    Set wsh = CreateObject("WScript.Shell")

    homeDir = ProjectDir()
    If Len(homeDir) = 0 Then
        MsgBox "MAILPLUS_HOME is not set." & vbCrLf & vbCrLf & _
               "Set it to your outlook-automation folder, for example:" & vbCrLf & _
               "    setx MAILPLUS_HOME ""C:\path\to\outlook-automation""" & vbCrLf & _
               "Then close and reopen Outlook.", vbExclamation, "Configuration Error"
        RunPowerShellScript = 1
        GoTo Cleanup2
    End If

    pyExe = PythonExe()
    scriptFile = ScriptPath()
    logsDir = homeDir & "\logs"

    If Not fso.FileExists(pyExe) Then
        MsgBox "Python not found:" & vbCrLf & pyExe & vbCrLf & vbCrLf & _
               "Create the virtual environment and install Playwright:" & vbCrLf & _
               "    python -m venv .venv" & vbCrLf & _
               "    .venv\Scripts\python -m pip install playwright" & vbCrLf & _
               "    .venv\Scripts\python -m playwright install chromium", vbExclamation, "Configuration Error"
        RunPowerShellScript = 1
        GoTo Cleanup2
    End If

    ' Ensure logs directory exists
    If Not fso.FolderExists(logsDir) Then
        fso.CreateFolder logsDir
    End If

    ' Write arguments to a temp JSON file to avoid cmd.exe escaping issues
    argsFile = logsDir & "\vba_args.json"
    Dim argsJson As String
    Dim escSender As String: escSender = Replace(senderEmail, "\", "\\")
    escSender = Replace(escSender, """", "\""")
    Dim escSubject As String: escSubject = Replace(subject, "\", "\\")
    escSubject = Replace(escSubject, """", "\""")
    escSubject = Replace(escSubject, vbCrLf, "\n")
    escSubject = Replace(escSubject, vbCr, "\n")
    escSubject = Replace(escSubject, vbLf, "\n")
    argsJson = "{""action"":""" & action & """,""sender"":""" & escSender & """,""subject"":""" & escSubject & """}"

    ' Write args as UTF-8 (FSO CreateTextFile uses ANSI and fails with
    ' runtime error 5 on unicode characters like emoji in subject/sender)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2                ' adTypeText
    stream.Charset = "utf-8"
    stream.Open
    stream.WriteText argsJson
    stream.SaveToFile argsFile, 2  ' adSaveCreateOverWrite
    stream.Close
    Set stream = Nothing

    ' Build command line for Python (only pass the args file path)
    cmd = """" & pyExe & """ """ & scriptFile & """ """ & argsFile & """"

    ' Run hidden (0 = hidden window, True = wait for completion)
    On Error Resume Next
    exitCode = wsh.Run(cmd, 0, True)

    If Err.Number <> 0 Then
        MsgBox "Failed to start Python. Check that " & pyExe & " is available.", vbExclamation, "Error"
        RunPowerShellScript = 1
        GoTo Cleanup2
    End If

    If exitCode = 0 Then
        RunPowerShellScript = 0
    Else
        MsgBox "Script failed (exit code " & exitCode & "). Check logs at:" & vbCrLf & _
                logsDir, vbExclamation, "Error"
        RunPowerShellScript = exitCode
    End If

Cleanup2:
    Set wsh = Nothing
End Function

'==============================================================
' Debug: Test configuration
'==============================================================
Public Sub TestConfig()
    Dim fso As Object
    Set fso = CreateObject("Scripting.FileSystemObject")

    Dim results As String
    Dim homeDir As String
    results = "MailPlus Automation - Configuration Check" & vbCrLf & vbCrLf

    homeDir = ProjectDir()
    If Len(homeDir) = 0 Then
        results = results & "[FAIL] MAILPLUS_HOME is not set." & vbCrLf
        results = results & "       Set it, then reopen Outlook:" & vbCrLf
        results = results & "       setx MAILPLUS_HOME ""C:\path\to\outlook-automation""" & vbCrLf
    Else
        results = results & "[OK] MAILPLUS_HOME = " & homeDir & vbCrLf

        If fso.FileExists(ScriptPath()) Then
            results = results & "[OK] Python script found" & vbCrLf
        Else
            results = results & "[MISSING] " & ScriptPath() & vbCrLf
        End If

        If fso.FileExists(PythonExe()) Then
            results = results & "[OK] venv Python found" & vbCrLf
        Else
            results = results & "[MISSING] " & PythonExe() & vbCrLf
            results = results & "       Create the venv + install Playwright first." & vbCrLf
        End If

        If fso.FileExists(homeDir & "\.env") Then
            results = results & "[OK] .env found" & vbCrLf
        Else
            results = results & "[WARN] .env not found (credentials missing)." & vbCrLf
        End If
    End If

    results = results & vbCrLf & "Quick Access Toolbar Buttons:" & vbCrLf
    results = results & "  Assign these macros:" & vbCrLf
    results = results & "  - Spam (forwards as attachment)" & vbCrLf
    results = results & "  - Block (adds to Synology block list)" & vbCrLf
    results = results & "  - Release (releases from MCP quarantine)" & vbCrLf

    MsgBox results, vbInformation, "Configuration Check"

    Set fso = Nothing
End Sub
