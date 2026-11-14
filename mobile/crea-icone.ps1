# Crea le icone PNG dell'app (180, 192, 512 px) da static\icona.svg con Edge senza finestra.
$qui = Split-Path -Parent $MyInvocation.MyCommand.Path
$radice = Split-Path -Parent $qui
$tmp = Join-Path $env:TEMP 'smartdesk-icone'
New-Item -ItemType Directory -Force $tmp | Out-Null
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
foreach ($n in @(512)) {  # le finestre piccole vengono tagliate: 180 e 192 si ricavano dalla 512 con ffmpeg
  $svg = [IO.File]::ReadAllText((Join-Path $radice 'static\icona.svg')) -replace 'width="512" height="512"', "width=`"$n`" height=`"$n`""
  [IO.File]::WriteAllText((Join-Path $tmp "icona$n.html"), "<!doctype html><html><body style='margin:0;overflow:hidden;background:transparent'>$svg</body></html>")
  $png = Join-Path $qui "app\icona-$n.png"
  Start-Process $edge -ArgumentList @('--headless=new', '--disable-gpu', "--user-data-dir=$tmp\profilo", "--window-size=$n,$n",
    '--hide-scrollbars', '--force-device-scale-factor=1', '--default-background-color=00000000', "--screenshot=$png", "file:///$($tmp -replace '\\','/')/icona$n.html") -Wait
  Write-Output "icona-$n.png: $((Get-Item $png).Length) byte"
}
foreach ($n in 180, 192) { ffmpeg -loglevel error -y -i (Join-Path $qui 'app\icona-512.png') -vf "scale=${n}:${n}:flags=lanczos" (Join-Path $qui "app\icona-$n.png") }
