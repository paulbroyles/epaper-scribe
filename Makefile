HA_HOST ?= homeassistant.local
HA_USER ?= root
CONFIG   = /config

.PHONY: deploy deploy-component deploy-blueprints

deploy: deploy-component deploy-blueprints

deploy-component:
	scp -r custom_components/epaper_scribe \
	    $(HA_USER)@$(HA_HOST):$(CONFIG)/custom_components/

deploy-blueprints:
	scp -r blueprints/automation/epaper_scribe \
	    $(HA_USER)@$(HA_HOST):$(CONFIG)/blueprints/automation/
	scp -r blueprints/script/epaper_scribe \
	    $(HA_USER)@$(HA_HOST):$(CONFIG)/blueprints/script/
