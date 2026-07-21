use scripting additions

property projectDir : "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
property pythonPath : "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
property portNumber : "5051"
property appURL : "http://localhost:5051/"
property pidFile : "/tmp/big_movers_server.pid"
property logFile : "/tmp/big_movers.log"
property controllerPath : projectDir & "/mac/big_movers_process.sh"
property serverPID : missing value
property ownershipWarningShown : false

on controllerCommand(verbName, maybePID)
	set commandText to "/bin/zsh " & quoted form of controllerPath & " " & quoted form of verbName & " " & quoted form of projectDir & " " & quoted form of pythonPath & " " & quoted form of portNumber & " " & quoted form of pidFile
	if verbName is "start" then
		set commandText to commandText & " " & quoted form of logFile
	else
		set commandText to commandText & " " & quoted form of (maybePID as text)
	end if
	set shellResult to do shell script commandText
	return shellResult
end controllerCommand

on firstLine(valueText)
	if valueText is "" then return ""
	return paragraph 1 of valueText
end firstLine

on readRetainedPID()
	try
		set valueText to do shell script "/bin/test -f " & quoted form of pidFile & " && /bin/cat " & quoted form of pidFile
		return my firstLine(valueText)
	on error
		return ""
	end try
end readRetainedPID

on openBrowser()
	do shell script "/usr/bin/open " & quoted form of appURL
end openBrowser

on run
	try
		set serverPID to my firstLine(my controllerCommand("start", missing value))
		set ownershipWarningShown to false
		my openBrowser()
	on error errMsg number errNum
		if errNum is 16 then
			set retainedPID to my readRetainedPID()
			if retainedPID is not "" then
				try
					my controllerCommand("status", retainedPID)
					set serverPID to retainedPID
					display notification "Startup cleanup timed out. Big Movers is retaining server PID " & retainedPID & ". Quit again to retry." with title "Big Movers"
					return
				on error statusMsg number statusNum
					if statusNum is 1 then
						try
							my controllerCommand("stop", retainedPID)
						on error
						end try
						set serverPID to missing value
						tell me to quit
						return
					end if
					set serverPID to retainedPID
					display notification statusMsg with title "Big Movers ownership warning"
					return
				end try
			end if
		end if
		set serverPID to missing value
		display dialog "Big Movers could not start." & return & return & errMsg & return & "Log: " & logFile buttons {"OK"} default button "OK" with icon stop
		tell me to quit
	end try
end run

on reopen
	if serverPID is not missing value then
		try
			my openBrowser()
		on error
		end try
	end if
end reopen

on idle
	if serverPID is missing value then return 2
	try
		my controllerCommand("status", serverPID)
		set ownershipWarningShown to false
	on error errMsg number errNum
		if errNum is 1 then
			set deadPID to serverPID
			try
				my controllerCommand("stop", deadPID)
			on error
			end try
			set serverPID to missing value
			tell me to quit
			return 2
		end if
		if ownershipWarningShown is false then
			display notification errMsg with title "Big Movers ownership warning"
			set ownershipWarningShown to true
		end if
	end try
	return 2
end idle

on quit
	if serverPID is missing value then continue quit
	try
		my controllerCommand("stop", serverPID)
		set serverPID to missing value
		set ownershipWarningShown to false
		continue quit
	on error errMsg number errNum
		display notification errMsg & " Log: " & logFile with title "Big Movers is still running"
		return
	end try
end quit
