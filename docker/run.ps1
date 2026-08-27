# Every test in this repository, in a container. One command, one exit code.
#
#   docker\run.ps1                 everything
#   docker\run.ps1 units sun       only those
#   docker\run.ps1 --list          what would run, and what would be skipped
#   docker\run.ps1 --skip-slow     leave out the ones that take minutes
#
# The same as `run.sh`, for a Windows shell. Kept as a second file rather than
# asking for WSL: the repository lives on an NTFS drive, and a container that
# mounts it directly is one fewer filesystem in the way.
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$image = 'weewx-evo-tests'

docker build -q -t $image -f (Join-Path $here 'Dockerfile') $here | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# No network: every test here runs without one, and one that quietly reaches
# the internet is one that fails on a train.
docker run --rm `
    --network none `
    -v "${repo}:/repo" `
    -e TZ=Europe/Berlin `
    $image @args
exit $LASTEXITCODE
