# Deployment (Member 5)

## Install as systemd services on the Pi

```bash
sudo cp watchdog/systemd/fdas-pipeline.service /etc/systemd/system/
sudo cp watchdog/systemd/fdas-watchdog.service /etc/systemd/system/
sudo cp watchdog/systemd/fdas-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fdas-pipeline
sudo systemctl enable --now fdas-watchdog
sudo systemctl enable --now fdas-ui
```

Both services run independently (`Restart=on-failure` on each) so a crash
in one doesn't take down the other — the watchdog specifically needs to
keep running even if the main pipeline dies, per the step-13 design.

## Checklist
- [ ] Confirm UPS HAT correctly reports power status; test a simulated
      power cut and confirm graceful continuation/restart
- [ ] Confirm both services auto-start on boot (`sudo reboot`, then
      `systemctl status fdas-pipeline fdas-watchdog`)
- [ ] Set up log rotation for the event DB and any file logs
      (`/etc/logrotate.d/`)
- [ ] Multi-day soak test (Week 7): leave running, monitor for missed
      heartbeats, memory leaks, or unexpected restarts
