BASENAME = instance-manager

COMMON_FILES = $(shell find ./src/common/ -type f -name '*')
APPLICATIONS = $(shell find ./src/applications/ -type f -name '*')
MAIN_SOURCES = $(shell find ./src/ -maxdepth 1 -type f -name '*.py')

SOURCES := $(COMMON_FILES) $(APPLICATIONS) $(MAIN_SOURCES)

.PHONY: clean

all: control instance-manager.service postinst $(SOURCES)
	mkdir -p $(BASENAME)/DEBIAN
	mkdir -p $(BASENAME)/usr/lib/instance-manager
	mkdir -p $(BASENAME)/lib/systemd/system
	mkdir -p $(BASENAME)/usr/local/bin
	mkdir -p $(BASENAME)/etc/chrony
	cp control postinst preinst $(BASENAME)/DEBIAN/.
	cp instance-manager.service $(BASENAME)/lib/systemd/system/.
	cp -r src/*.py $(BASENAME)/usr/lib/instance-manager/.
	cp -Lr src/common $(BASENAME)/usr/lib/instance-manager/.
	cp -Lr src/applications $(BASENAME)/usr/lib/instance-manager/.
	rm -rf $(BASENAME)/usr/lib/instance-manager/common/__pycache__
	rm -rf $(BASENAME)/usr/lib/instance-manager/applications/__pycache__
	cp -p im $(BASENAME)/usr/local/bin/.
	cp chrony.conf $(BASENAME)/etc/chrony/chrony.conf
	dpkg-deb --build $(BASENAME)

clean:
	rm -rf $(BASENAME) $(BASENAME).deb
