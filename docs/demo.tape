# Records the README demo GIF with vhs (https://github.com/charmbracelet/vhs):
#   vhs docs/demo.tape
# Uses synthetic data only, so no real prompts end up in the recording.

Output docs/demo.gif
Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 640
Set Theme "Catppuccin Mocha"

Hide
Type "export TOKCAST_HOME=/tmp/tokcast-demo/db && tokcast synth --out /tmp/tokcast-demo --force > /dev/null && tokcast ingest --path /tmp/tokcast-demo/logs > /dev/null && clear"
Enter
Sleep 4s
Show

Type 'tokcast predict "fix the login bug in auth.py" --model opus --effort high'
Sleep 500ms
Enter
Sleep 5s

Type 'tokcast predict "refactor the export job" --context 250k --no-compare'
Sleep 500ms
Enter
Sleep 5s
