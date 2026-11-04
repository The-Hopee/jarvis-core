$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    Add-Type -AssemblyName System.Speech
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
    try {
        $russian = $speaker.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'ru-RU' } | Select-Object -First 1
        if ($russian) { $speaker.SelectVoice($russian.VoiceInfo.Name) }
        if ($request.voice) { $speaker.SelectVoice([string]$request.voice) }
        $speaker.Rate = 0
        if ($request.output_path) {
            $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
            $speaker.SetOutputToWaveFile([string]$request.output_path, $format)
        }
        $speaker.Speak([string]$request.text)
        @{ ok = $true; voice = $speaker.Voice.Name; russian_available = [bool]$russian } | ConvertTo-Json -Compress
    } finally { $speaker.Dispose() }
} catch {
    @{ ok = $false; error = 'Windows speech synthesis failed' } | ConvertTo-Json -Compress
    exit 1
}
