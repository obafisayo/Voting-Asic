module mod05_fsm (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        data_ready,
    input  wire        validate_done,
    input  wire        id_valid,
    input  wire        check_done,
    input  wire        is_duplicate,
    input  wire [2:0]  candidate_in,
    output reg         check_en,
    output reg         vote_en,
    output wire [2:0]  candidate_sel,
    output reg  [2:0]  status_out
);

    localparam IDLE=3'b000, VALIDATING=3'b001, CHECKING=3'b010,
               VOTE_CAST=3'b011, DUPLICATE=3'b100, INVALID=3'b101;

    reg [2:0] state, next_state;

    // State register
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= IDLE;
        else        state <= next_state;
    end

    // Next-state logic (combinational)
    always @(*) begin
        next_state = state;
        case (state)
            IDLE:       if (data_ready)    next_state = VALIDATING;
            VALIDATING: if (validate_done) next_state = id_valid ? CHECKING : INVALID;
            CHECKING:   if (check_done)    next_state = is_duplicate ? DUPLICATE : VOTE_CAST;
            VOTE_CAST, DUPLICATE, INVALID: next_state = IDLE;
            default:    next_state = IDLE;
        endcase
    end

    // check_en is registered and pulses for exactly ONE cycle on entry to
    // CHECKING.  Without this, the FSM stays in CHECKING for 2 cycles and
    // the duplicate_checker would fire twice — incorrectly flagging the first
    // vote of a valid voter as a duplicate on the second fire.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            check_en <= 1'b0;
        else
            check_en <= (next_state == CHECKING) && (state != CHECKING);
    end

    // vote_en and status_out are purely combinational on state
    always @(*) begin
        vote_en    = (state == VOTE_CAST);
        status_out = state;
    end

    // candidate_sel always mirrors candidate_in so the host can select any
    // candidate via ui_in[2:0] during IDLE to read its tally on uo_out[7:5].
    assign candidate_sel = candidate_in;

endmodule
