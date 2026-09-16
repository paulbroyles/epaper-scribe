# Local deployment to Home Assistant
# Set HA_HOST to your HA hostname or IP, e.g.:
#   make deploy HA_HOST=homeassistant.local
#   make deploy HA_HOST=192.168.1.100
#
# The HA_USER defaults to root (standard for HA OS SSH access).
# AppDaemon apps path assumes the default add-on ID; adjust if yours differs.

HA_HOST ?= homeassistant.local
HA_USER ?= root
AD_APPS_DIR = /addon_configs/a0d7b954_appdaemon/apps
HA_CONFIG_DIR = /config

.PHONY: deploy deploy-appdaemon deploy-ha-config

deploy: deploy-appdaemon deploy-ha-config

deploy-appdaemon:
	scp appdaemon-apps/display_supervisor.py \
	    appdaemon-apps/now_playing.py \
	    appdaemon-apps/saints_day.py \
	    appdaemon-apps/apps.yaml \
	    $(HA_USER)@$(HA_HOST):$(AD_APPS_DIR)/

deploy-ha-config:
	scp ha-config/inputs.yaml  $(HA_USER)@$(HA_HOST):$(HA_CONFIG_DIR)/inputs.yaml
	scp ha-config/templates.yaml $(HA_USER)@$(HA_HOST):$(HA_CONFIG_DIR)/templates.yaml
