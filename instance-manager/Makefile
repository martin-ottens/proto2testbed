BASENAME = instance-manager

COMMON_FILES = $(shell find ./common/ -type f -name '*')

.PHONY: clean

all: manager_main.py control instance-manager.service postinst $(COMMON_FILES)
	mkdir -p $(BASENAME)/DEBIAN
	mkdir -p $(BASENAME)/usr/lib/instance-manager
	mkdir -p $(BASENAME)/lib/systemd/system
	cp control postinst $(BASENAME)/DEBIAN/.
	cp instance-manager.service $(BASENAME)/lib/systemd/system/.
	cp manager_main.py $(BASENAME)/usr/lib/instance-manager/.
	cp -Lr common $(BASENAME)/usr/lib/instance-manager/.
	dpkg-deb --build $(BASENAME)

clean:
	rm -rf $(BASENAME) $(BASENAME).deb
