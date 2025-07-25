macro "Auto-Overlay Pressure" {
    run("Show Info...");
    n = nSlices;
    for (i=1; i<=n; i++) {
        setSlice(i);
        meta = getMetadata("Info");
        lines = split(meta, "\n");
        for (j=0; j<lines.length; j++) {
            if (startsWith(lines[j], "Pressure=")) {
                val = substring(lines[j], 9);
                run("Add Text...", "text=" + val + " mmHg x=10 y=20 font=18");
                break;
            }
        }
    }
}
