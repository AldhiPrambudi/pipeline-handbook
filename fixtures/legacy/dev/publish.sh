#!/bin/sh
# Definition-only fixture. The scanner must never run this command.
# handbook: working-directory=.
psql -f publish.sql
