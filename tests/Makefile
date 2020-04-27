include ../makefile.inc

MODULE_NAME=torchbraid_test

LIB_NAME=$(MODULE_NAME).$(POSTFIX)

all: $(LIB_NAME)

$(LIB_NAME): ${MODULE_NAME}.pyx
	XBRAID_ROOT=$(XBRAID_ROOT) CC=mpicc $(PYTHON) setup.py install --record installed_files.txt

clean:
	rm -fr $(MODULE_NAME).c $(MODULE_NAME).h build *.html __pycache__/ $(LIB_NAME)

uninstall:
	cat installed_files.txt | xargs rm -fr # remove installation
	rm -fr installed_files.txt

tests test:
	$(MPIRUN) -n 3 $(PYTHON) test_bwd.py