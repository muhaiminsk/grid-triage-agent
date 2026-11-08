#!/bin/bash
echo "loading calibration tables into memory"
( head -c 300m /dev/zero; sleep 420 ) | tail > /dev/null
