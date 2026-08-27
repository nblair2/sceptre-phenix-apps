## phenix ignition app (perspective client)
$status = $null
while ($status -ne '200') {
    $status = curl.exe -s -o NUL -w '%{http_code}' '${url}'
    if ($status -ne '200') {
        echo "[ IGNITION ] Gateway not ready yet, retrying in 10 seconds..."
        Start-Sleep -Seconds 10
    }
}
echo "[ IGNITION ] Gateway ready, starting firefox"
Start-Process 'firefox.exe' '${url}'
echo "[ IGNITION ] Gateway ready, firefox started, all done!"
