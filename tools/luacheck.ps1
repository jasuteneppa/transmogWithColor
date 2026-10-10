# Minimal Lua block-balance checker: strips comments and strings, then matches
# block openers (function / if / do) against `end`, and repeat against until.
# Not a parser -- it catches the realistic hand-editing failure (a missing or
# extra `end`) and reports where the nesting first goes wrong.
param([string[]]$Files)

foreach ($f in $Files) {
    $src = [IO.File]::ReadAllText($f)
    $out = New-Object Text.StringBuilder
    $i = 0; $n = $src.Length; $line = 1
    $lineOf = New-Object Collections.Generic.List[int]

    while ($i -lt $n) {
        $ch = $src[$i]
        $two = if ($i + 1 -lt $n) { $src.Substring($i, 2) } else { '' }

        if ($two -eq '--') {
            # long comment --[[ ... ]] or --[=[ ... ]=]
            $m = [regex]::Match($src.Substring($i), '^--\[(=*)\[')
            if ($m.Success) {
                $close = ']' + $m.Groups[1].Value + ']'
                $end = $src.IndexOf($close, $i + $m.Length)
                if ($end -lt 0) { $end = $n } else { $end += $close.Length }
                $line += ([regex]::Matches($src.Substring($i, $end - $i), "`n")).Count
                $i = $end; continue
            }
            while ($i -lt $n -and $src[$i] -ne "`n") { $i++ }
            continue
        }

        if ($ch -eq '[') {
            $m = [regex]::Match($src.Substring($i), '^\[(=*)\[')
            if ($m.Success) {
                $close = ']' + $m.Groups[1].Value + ']'
                $end = $src.IndexOf($close, $i + $m.Length)
                if ($end -lt 0) { $end = $n } else { $end += $close.Length }
                $line += ([regex]::Matches($src.Substring($i, $end - $i), "`n")).Count
                $i = $end; continue
            }
        }

        if ($ch -eq '"' -or $ch -eq "'") {
            $q = $ch; $i++
            while ($i -lt $n -and $src[$i] -ne $q) {
                if ($src[$i] -eq '\') { $i++ }
                if ($i -lt $n -and $src[$i] -eq "`n") { $line++ }
                $i++
            }
            $i++
            [void]$out.Append(' STR ')
            continue
        }

        if ($ch -eq "`n") { $line++ }
        [void]$out.Append($ch)
        $lineOf.Add($line) | Out-Null
        $i++
    }

    # Re-scan the stripped text keeping line numbers by walking it line by line.
    $stripped = $out.ToString()
    $depth = 0; $repeatDepth = 0; $ln = 0; $bad = $null
    foreach ($l in ($stripped -split "`n")) {
        $ln++
        foreach ($w in [regex]::Matches($l, '\b[A-Za-z_]\w*\b')) {
            switch ($w.Value) {
                'function' { $depth++ }
                'if'       { $depth++ }
                'do'       { $depth++ }
                'end'      { $depth--; if ($depth -lt 0 -and -not $bad) { $bad = "extra 'end' at line $ln" } }
                'repeat'   { $repeatDepth++ }
                'until'    { $repeatDepth-- }
            }
        }
    }

    $name = Split-Path $f -Leaf
    if ($bad) { "FAIL  $name : $bad" }
    elseif ($depth -ne 0) { "FAIL  $name : block depth ends at $depth (missing $depth 'end')" }
    elseif ($repeatDepth -ne 0) { "FAIL  $name : repeat/until unbalanced ($repeatDepth)" }
    else { "ok    $name" }
}
