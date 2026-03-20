@echo off
echo Starting git operations...
git add .
git commit -m "Upload Version 4.0"
git tag version4.0
git push origin version-4.0
git push origin version4.0
echo DONE > git_done.txt
