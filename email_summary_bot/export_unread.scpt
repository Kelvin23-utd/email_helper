-- Export unread Apple Mail messages within a recent lookback window.
on run argv
  if (count of argv) is not 3 then
    error "Usage: osascript export_unread.scpt LOOKBACK_MINUTES MAX_EMAILS OUTPUT_PATH"
  end if

  set lookbackMinutes to (item 1 of argv) as integer
  set maxEmails to (item 2 of argv) as integer
  set outputPath to item 3
  if lookbackMinutes < 1 then set lookbackMinutes to 60
  if maxEmails < 1 then set maxEmails to 15

  set cutoffDate to (current date) - lookbackMinutes * minutes
  set collectedRows to {"sender\tsubject\treceived_at\tbody"}
  set writtenCount to 0

  tell application "Mail"
    set inboxList to every inbox
    repeat with eachInbox in inboxList
      set candidateMessages to (messages of eachInbox whose read status is false and date received >= cutoffDate)
      repeat with eachMessage in candidateMessages
        set senderName to my clean_text(sender of eachMessage)
        set subjectLine to my clean_text(subject of eachMessage)
        set receivedDate to my iso8601(date received of eachMessage)
        set bodyText to my clean_text(content of eachMessage)
        set end of collectedRows to senderName & tab & subjectLine & tab & receivedDate & tab & bodyText
        set writtenCount to writtenCount + 1
        if writtenCount ≥ maxEmails then exit repeat
      end repeat
      if writtenCount ≥ maxEmails then exit repeat
    end repeat
  end tell

  set AppleScript's text item delimiters to linefeed
  set exportText to collectedRows as string
  set AppleScript's text item delimiters to ""

  my write_text(exportText, outputPath)
end run

on clean_text(rawText)
  set theString to rawText as string
  set theString to my replace_text(theString, return, " ")
  set theString to my replace_text(theString, linefeed, " ")
  set theString to my replace_text(theString, tab, " ")
  return theString
end clean_text

on replace_text(theText, findString, replaceString)
  set AppleScript's text item delimiters to findString
  set tempList to every text item of theText
  set AppleScript's text item delimiters to replaceString
  set newText to tempList as string
  set AppleScript's text item delimiters to ""
  return newText
end replace_text

on iso8601(theDate)
  set y to year of theDate as integer
  set m to month of theDate as integer
  set d to day of theDate as integer
  set totalSeconds to time of theDate
  set hh to totalSeconds div 3600
  set mm to (totalSeconds mod 3600) div 60
  set ss to totalSeconds mod 60
  return my pad4(y) & "-" & my pad2(m) & "-" & my pad2(d) & "T" & my pad2(hh) & ":" & my pad2(mm) & ":" & my pad2(ss) & "Z"
end iso8601

on pad2(n)
  set s to n as string
  if n < 10 then
    return "0" & s
  else
    return s
  end if
end pad2

on pad4(n)
  set s to n as string
  if n < 10 then return "000" & s
  if n < 100 then return "00" & s
  if n < 1000 then return "0" & s
  return s
end pad4

on write_text(theText, outputPath)
  set fileRef to open for access (outputPath as POSIX file) with write permission
  try
    set eof of fileRef to 0
    write theText to fileRef starting at 0
  on error errMsg number errNum
    close access fileRef
    error errMsg number errNum
  end try
  close access fileRef
end write_text
