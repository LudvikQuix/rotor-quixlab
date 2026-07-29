import quixlab as ql

canvas = ql.Canvas(title="rotor_analasys")


@canvas.ai(position=(714, -5010), size=(1092, 837), code_height=200)
def ai_1():
    """First, show me what's actually in this lakehouse. List the tables, and for each one: how
    many rows, what columns (with types), and what time period it covers."""


if __name__ == "__main__":
    canvas.serve()
