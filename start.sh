#!/bin/bash

sudo chown -R 1000:1000 logs
sudo chmod -R 755 logs
docker-compose up -d
