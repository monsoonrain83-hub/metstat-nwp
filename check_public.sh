#!/bin/sh
# Fails if the public repo contains anything that must stay private.
bad=0
for p in 'clim_db' 'CLIM_PACK' 'CLIM_META' 'site_src.zip' 'clim_tmean' 'mx_config' 'nwp_upload.php' 'metstat_data'; do
  hits=$(git ls-files | grep -i -- "$p" || true)
  [ -n "$hits" ] && { echo "FORBIDDEN FILE ($p): $hits"; bad=1; }
done
hits=$(git ls-files | grep -v '^check_public.sh$' | grep -v '^\.github/' | xargs grep -nIE '(upload_key|password|passwd|secret|api[_-]?key)["'"'"']?[[:space:]]*[=:][[:space:]]*["'"'"'][^"'"'"']{6,}' 2>/dev/null || true)
[ -n "$hits" ] && { echo "POSSIBLE SECRET:"; echo "$hits"; bad=1; }
big=$(git ls-files | xargs ls -l 2>/dev/null | awk '$5>5000000{print $9" "$5}')
[ -n "$big" ] && { echo "LARGE FILE (check it is not data): $big"; bad=1; }
[ $bad -eq 0 ] && echo "public repo check OK"
exit $bad
