BASENAME = instance-manager

COMMON_FILES = $(shell find ./common/ -type f -name '*')
APPLICATIONS = $(shell find ./applications/ -type f -name '*')
MAIN_SOURCES = $(shell find . -maxdepth 1 -type f -name '*.py')

SOURCES := $(COMMON_FILES) $(APPLICATIONS) $(MAIN_SOURCES)

.PHONY: clean

all: control instance-manager.service postinst $(SOURCES)
	mkdir -p $(BASENAME)/DEBIAN
	mkdir -p $(BASENAME)/usr/lib/instance-manager
	mkdir -p $(BASENAME)/lib/systemd/system
	mkdir -p $(BASENAME)/usr/local/bin
	cp control postinst $(BASENAME)/DEBIAN/.
	cp instance-manager.service $(BASENAME)/lib/systemd/system/.
	cp -r *.py applications/ $(BASENAME)/usr/lib/instance-manager/.
	cp -Lr common $(BASENAME)/usr/lib/instance-manager/.
	cp -p im $(BASENAME)/usr/local/bin/.
	dpkg-deb --build $(BASENAME)

clean:
	rm -rf $(BASENAME) $(BASENAME).deb
