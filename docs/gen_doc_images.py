import json
import os
import re
import tempfile
from io import StringIO
from xml.dom import minidom

import pexpect
from rich import text
from rich.console import Console
from rich.terminal_theme import MONOKAI

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
gdb_common = 'gdb --quiet --ex "source ' + parent_dir + '/gdbinit.py"'


def annotate_svg(svg_path, annotations=[]):
    doc = minidom.parse(svg_path)
    # get all <text> elements
    text_elements = doc.getElementsByTagName("text")
    for annotation in annotations:
        min_x = float("inf")
        min_y = float("inf")
        max_x = -1.0
        max_y = -1.0
        text_parent = None
        # parse annotation["match"] as regexes
        regexes = [re.compile(regex) for regex in annotation["match"]]
        print(regexes)
        for text_element in text_elements:
            # get the text
            text = text_element.firstChild.nodeValue
            # if any of the regexes match, add the annotation
            # print("matching: " + text)
            if any(regex.search(text) for regex in regexes):
                print(text_element.toxml())
                x1 = float(text_element.getAttribute("x"))
                y1 = float(text_element.getAttribute("y"))
                x2 = x1 + float(text_element.getAttribute("width") or "0")
                y2 = y1 + float(text_element.getAttribute("height") or "0")
                min_x = min(min_x, x1)
                min_y = min(min_y, y1)
                max_x = max(max_x, x2)
                max_y = max(max_y, y2)
                text_parent = text_element.parentNode
                print("FOUND TEXT: " + text)
        print("min_x: " + str(min_x))
        print("min_y: " + str(min_y))
        print("max_x: " + str(max_x))
        print("max_y: " + str(max_y))
        # add the annotation
        if min_x != float("inf") or min_y != float("inf") or max_x != -1.0 or max_y != -1.0:
            print("ADDING ANNOTATION")
            rect = doc.createElement("rect")
            rect.setAttribute("x", str(min_x))
            rect.setAttribute("y", str(min_y))
            rect.setAttribute("width", str(max_x - min_x))
            rect.setAttribute("height", str(max_y - min_y))
            rect.setAttribute("fill", "none")
            rect.setAttribute("stroke", "red")
            rect.setAttribute("stroke-width", "3")
            text_parent.appendChild(rect)
    with open(svg_path, "w") as f:
        f.write(doc.toxml())


# runs the given command in a pty and saves a screenshot of the output
def render_cmd(cmd, stdin_input, outfile, cmd_display_as=None):
    if cmd_display_as is None:
        cmd_display_as = cmd.replace(gdb_common, "gdb")
    sanitized_env = {k: v for k, v in os.environ.items() if k in ["HOME", "LANG", "LC_ALL", "PATH"]}
    # sanitized_env["TERM"] = "xterm-256color"

    child = pexpect.spawn(
        cmd,
        env=sanitized_env,
    )
    output = []
    # send the input to the command
    child.sendline(stdin_input)
    while True:
        try:
            data = child.read_nonblocking(size=1, timeout=2)
            output.append(data)
        except pexpect.TIMEOUT:
            # kill the process
            child.kill(9)
        except pexpect.EOF:
            out_str = b"".join(output).decode("utf-8")
            out_str_lines = out_str.splitlines()
            # start from '---START_RENDER---'
            try:
                out_str_lines = out_str_lines[out_str_lines.index("'---START_RENDER---'") + 1 :]
            except ValueError:
                pass
            # end at '---END_RENDER---'
            try:
                out_str_lines = out_str_lines[: out_str_lines.index("'---END_RENDER---'")]
            except ValueError:
                pass

            out_str = "$ " + cmd_display_as + "\n" + "\n".join(out_str_lines)
            console = Console(record=True, file=StringIO())
            richText = text.Text.from_ansi(out_str)
            console.print(richText)
            console.save_svg(outfile, theme=MONOKAI, title="pwndbg")
            annotations = []
            for line in stdin_input.splitlines():
                if line.startswith("#ANNOTATE "):
                    # reove the #ANNOTATE: prefix
                    annotations.append(json.loads(line[10:]))

            annotate_svg(outfile, annotations)
            break


if __name__ == "__main__":
    # open FEATURES.md and find all the code blocks
    with open("FEATURES.src.md", "r") as f:
        lines = f.readlines()
        output = []  # processed markdown lines
        last_title = "untitled"  # hold the last title, so we can name the generated images nicely
        i = 0

        bin_path = None  # path to the last compiled binary

        while i < len(lines):
            if lines[i].startswith("```pwndbg"):
                # the command is everything after the first space
                gdb_cmd = lines[i].split(" ", 1)[1].strip()
                gdb_cmd = gdb_cmd.replace("$GDB", gdb_common).replace("$BIN", bin_path or "$BIN")
                gdb_input = []
                # read until the next code block
                j = i + 1
                while not lines[j].startswith("```"):
                    gdb_input.append(lines[j])
                    j += 1
                j += 1
                print("Running GDB: " + gdb_cmd)
                # render_cmd
                render_cmd(
                    cmd=gdb_cmd,
                    stdin_input="".join(gdb_input).strip(),
                    outfile=parent_dir + "/docs/images/" + last_title + ".svg",
                )
                # add the image to the output
                output.append("![](images/" + last_title + ".svg)\n")
                i = j
            else:

                # compile c programs which specify a command to compile afer ```c
                if lines[i].startswith("```c"):
                    compile_cmd = lines[i].split(" ", 1)[1].strip()
                    c_source = []
                    j = i + 1
                    while not lines[j].startswith("```"):
                        c_source.append(lines[j])
                        j += 1
                    # save the source to a temp file
                    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".c") as f:
                        f.write("".join(c_source))
                    bin_path = f.name + ".out"
                    # compile the source
                    cmd_to_compile = compile_cmd.replace("$BIN", bin_path).replace("$IN", f.name)
                    print("Compiling: " + cmd_to_compile)
                    os.system(cmd_to_compile)
                    bin_path = f.name + ".out"

                if lines[i].startswith("#"):
                    last_title = (
                        lines[i].replace("#", "").strip().replace(" ", "_").replace("`", "").lower()
                    )
                output.append(lines[i])
            i += 1
    # write the output to FEATURES.md
    with open("FEATURES.md", "w") as f:
        f.writelines(output)
